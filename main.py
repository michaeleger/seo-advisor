"""
SEO Advisor — on-demand pipeline (no Claude API calls):

  1) Google Search Console (free API / OAuth) → worst-performing posts
  2) WordPress content + per-page GSC queries
  3) Optional local LLM keyword pass (--with-local-llm)
  4) Write a Markdown report you paste into Claude for final polish

Outputs:
  reports/seo_report_YYYY-MM-DD.md   ← primary handoff for Claude
  reports/seo_report_YYYY-MM-DD.html ← browser-friendly view
  reports/seo_briefing_YYYY-MM-DD.json ← machine-readable copy
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import date
from pathlib import Path

import analyzer
import bing_webmaster
import briefing
import config
import db
import gsc
import keyword_planner
import pagespeed
import report
import seo_advisor
import wp_client

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "SEO Advisor: GSC worst posts → Claude handoff report "
            "(optional local keyword LLM)."
        ),
    )
    p.add_argument(
        "--no-cooldown",
        action="store_true",
        help="Re-include pages even if reported within COOLDOWN_DAYS.",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=None,
        metavar="N",
        help=f"Worst N posts to include (default: {config.MAX_POSTS_TO_ANALYZE}).",
    )
    p.add_argument(
        "--model",
        default=None,
        metavar="NAME",
        help="Local Ollama model override (only with --with-local-llm).",
    )
    p.add_argument(
        "--with-local-llm",
        action="store_true",
        help=(
            "Run the optional local keyword LLM (Ollama) before writing the report. "
            "Default is OFF — GSC + WordPress data is enough for Claude."
        ),
    )
    p.add_argument(
        "--demo",
        action="store_true",
        help=(
            "Smoke-test without GSC: live WordPress + synthetic metrics "
            "(still writes the handoff report)."
        ),
    )
    p.add_argument("-v", "--verbose", action="store_true", help="Debug logging.")
    return p.parse_args(argv)


def _demo_low_performers(limit: int) -> list[dict]:
    import requests

    base = config.WP_SITE_URL.rstrip("/")
    try:
        resp = requests.get(
            f"{base}/wp-json/wp/v2/posts",
            params={"per_page": max(limit, 1), "_fields": "link,title"},
            timeout=20,
            allow_redirects=True,
        )
        resp.raise_for_status()
        posts = resp.json()
    except Exception as exc:
        raise SystemExit(f"Demo mode could not fetch WordPress posts from {base}: {exc}")

    if not posts:
        raise SystemExit("Demo mode: WordPress returned no posts.")

    templates = [
        {"clicks": 3, "impressions": 420, "ctr": 0.007, "position": 18.4},
        {"clicks": 1, "impressions": 210, "ctr": 0.005, "position": 22.1},
        {"clicks": 5, "impressions": 680, "ctr": 0.007, "position": 15.8},
    ]
    rows = []
    for i, p in enumerate(posts[:limit]):
        m = templates[i % len(templates)]
        rows.append({
            "page": p["link"],
            "clicks": m["clicks"],
            "impressions": m["impressions"],
            "ctr": m["ctr"],
            "position": m["position"],
            "reasons": [
                f"Low CTR ({m['ctr']*100:.1f}% vs {config.MAX_CTR*100:.0f}% threshold) [demo]",
                f"Weak ranking (avg position {m['position']:.1f}) [demo]",
            ],
        })
    return rows


def _demo_queries(title: str) -> list[dict]:
    words = [w.lower() for w in title.split() if len(w) > 3][:4]
    seed = " ".join(words) if words else "health tips"
    return [
        {"query": seed, "clicks": 2, "impressions": 180, "ctr": 0.011, "position": 14.2},
        {"query": f"{seed} benefits", "clicks": 0, "impressions": 95, "ctr": 0.0, "position": 21.0},
        {"query": f"how to {seed}", "clicks": 1, "impressions": 70, "ctr": 0.014, "position": 18.5},
    ]


def apply_runtime_overrides(args: argparse.Namespace) -> None:
    if args.model:
        config.OLLAMA_MODEL = args.model
    if args.limit is not None:
        if args.limit < 1:
            raise SystemExit("--limit must be >= 1")
        config.MAX_POSTS_TO_ANALYZE = args.limit
    if args.with_local_llm:
        config.USE_LOCAL_LLM = True


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def collect_worst_posts(args: argparse.Namespace) -> list[dict]:
    if args.demo:
        log.warning("DEMO mode: synthetic GSC metrics (not production).")
        return _demo_low_performers(config.MAX_POSTS_TO_ANALYZE)

    # WordPress + RankMath first (drives improvable-first prioritization)
    log.info("Stage 0 — WordPress catalog + RankMath scores …")
    wp_posts: list[dict] = []
    try:
        wp_posts = wp_client.list_content_with_rankmath(max_items=300)
        n_scored = sum(
            1
            for p in wp_posts
            if (p.get("rankmath") or {}).get("seo_score") is not None
        )
        log.info("  %d WP posts/pages; %d with RankMath scores.", len(wp_posts), n_scored)
        if wp_posts and n_scored == 0:
            log.warning(
                "  No real RankMath scores found. These are NOT the Post Studio "
                "AI audit scores. To read plugin scores, set WP_APP_USER + "
                "WP_APP_PASSWORD (Application Password with editor access) so "
                "we can call GET /wp-json/rankmath/v1/links/posts — or install "
                "wordpress-plugin/eager-rankmath-rest.php as an mu-plugin."
            )
    except Exception as exc:
        log.warning("  WP catalog failed (continuing with GSC only): %s", exc)

    log.info(
        "Stage 1 — Google Search Console for %s (last %d days) …",
        config.GSC_SITE_URL,
        config.DATE_RANGE_DAYS,
    )
    try:
        page_metrics = gsc.get_page_metrics()
    except Exception as exc:
        log.error("GSC auth/API failed: %s", exc)
        log.error("Re-authorize: python authorize.py  (from RDP desktop on 5by5)")
        raise SystemExit(1) from exc

    log.info("  %d pages found in Search Console.", len(page_metrics))

    if args.no_cooldown:
        excluded: set[str] = set()
        log.info("  Cooldown disabled (--no-cooldown).")
    else:
        excluded = db.cooldown_urls(page_metrics, config.COOLDOWN_DAYS)
        log.info(
            "  %d page(s) skipped (within %d-day cooldown).",
            len(excluded),
            config.COOLDOWN_DAYS,
        )

    log.info(
        "Prioritizing improvable posts (RankMath tiers under %s, then GSC) cap=%d …",
        config.RANKMATH_SKIP_SCORE,
        config.MAX_POSTS_TO_ANALYZE,
    )
    return analyzer.identify_low_performers(
        page_metrics, excluded_urls=excluded, wp_posts=wp_posts
    )


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    apply_runtime_overrides(args)
    db.init_db()
    os.makedirs(config.REPORTS_DIR, exist_ok=True)

    today = date.today().isoformat()
    report_md = Path(config.REPORTS_DIR) / f"seo_report_{today}.md"
    report_html = Path(config.REPORTS_DIR) / f"seo_report_{today}.html"
    briefing_json = Path(config.REPORTS_DIR) / f"seo_briefing_{today}.json"

    log.info(
        "SEO Advisor — worst %d pages → Claude handoff (%s)",
        config.MAX_POSTS_TO_ANALYZE,
        config.local_llm_label(),
    )

    low_performers = collect_worst_posts(args)
    if not low_performers:
        log.info(
            "No eligible low-performing posts found. "
            "Try --no-cooldown, lower MIN_IMPRESSIONS, or raise DATE_RANGE_DAYS."
        )
        sys.exit(0)

    log.info("Found %d post(s) to package for Claude (improvable-first).", len(low_performers))
    for i, m in enumerate(low_performers, 1):
        rm_score = m.get("rankmath_score")
        rm_s = f"{rm_score}/100" if rm_score is not None else "n/a"
        log.info(
            "  %2d. RM=%-6s tier=%s  impr=%4d clk=%3d pos=%5.1f  %s",
            i,
            rm_s,
            m.get("rankmath_tier_label") or "?",
            int(m["impressions"]),
            int(m["clicks"]),
            m["position"],
            m.get("wp_title") or m["page"],
        )

    # ── Stage 2: sitewide GSC context (once) ─────────────────────────────────
    site_context: dict = {}
    if not args.demo:
        log.info("Stage 2a — full sitewide GSC extract …")
        try:
            site_context = gsc.get_site_context()
            log.info(
                "  opportunities=%d cannibal=%d countries=%d appearance=%d "
                "monthly_points=%d top_queries=%d",
                len(site_context.get("query_opportunities") or []),
                len(site_context.get("cannibalization") or []),
                len(site_context.get("countries") or []),
                len(site_context.get("search_appearance") or []),
                len(site_context.get("monthly_trend") or []),
                len(site_context.get("top_queries_with_pages") or []),
            )
        except Exception as exc:
            log.warning("  Sitewide GSC context failed (continuing): %s", exc)
            site_context = {}

    # ── Stage 2b: WordPress + per-page GSC enrichments (+ optional local LLM)
    use_llm = config.USE_LOCAL_LLM
    log.info(
        "Stage 2b — WordPress + full per-page GSC (%s)",
        config.local_llm_label(),
    )

    results: list[dict] = []
    pending_state: list[tuple[str, dict]] = []
    for i, metrics in enumerate(low_performers, 1):
        url = metrics["page"]
        log.info("[%d/%d] %s", i, len(low_performers), url)

        try:
            post = wp_client.get_post_content(url)
            if not post:
                log.warning("  WordPress content not found — including GSC-only stub.")
                slug = url.rstrip("/").split("/")[-1].replace("-", " ")
                post = {
                    "id": None,
                    "title": slug.title() or url,
                    "url": url,
                    "content_plain": "",
                    "rankmath": {},
                    "type": "unknown",
                }
            else:
                log.info("  Title: %s", post["title"])

            if args.demo:
                queries = _demo_queries(post["title"])
                period: dict = {}
                devices: list = []
                countries: list = []
                monthly_trend: list = []
            else:
                enrich = gsc.collect_page_enrichment(url)
                queries = enrich.get("queries") or []
                period = enrich.get("period_comparison") or {}
                devices = enrich.get("devices") or []
                countries = enrich.get("countries") or []
                monthly_trend = enrich.get("monthly_trend") or []
            log.info(
                "  queries=%d devices=%d countries=%d months=%d",
                len(queries),
                len(devices),
                len(countries),
                len(monthly_trend),
            )

            prev_state = db.get_page_state(url)
            prev_metrics = prev_state["last_metrics"] if prev_state else None

            analysis = None
            if use_llm:
                log.info("  Local LLM keyword pass …")
                analysis = seo_advisor.recommend_keywords(metrics, queries, post)
                if analysis:
                    nkw = len(analysis.get("target_keywords") or [])
                    log.info(
                        "  ✓ primary=%r (%d keywords)",
                        analysis.get("primary_keyword"),
                        nkw,
                    )
                else:
                    log.warning("  ✗ Local keyword pass failed for this post.")

            # Carry RankMath priority fields onto the post for the report
            if metrics.get("rankmath_score") is not None or metrics.get("focus_keyword"):
                rm = dict(post.get("rankmath") or {})
                if metrics.get("rankmath_score") is not None:
                    rm["seo_score"] = metrics["rankmath_score"]
                if metrics.get("focus_keyword"):
                    rm["focus_keyword"] = metrics["focus_keyword"]
                post["rankmath"] = rm

            results.append({
                "metrics": metrics,
                "post": post,
                "analysis": analysis,
                "queries": queries,
                "period_comparison": period,
                "devices": devices,
                "countries": countries,
                "monthly_trend": monthly_trend,
                "prev_metrics": prev_metrics,
            })
            # Defer the cooldown write until the report is actually written,
            # so a crash mid-run doesn't put pages into cooldown with no
            # delivered report.
            pending_state.append((url, dict(metrics)))

        except RuntimeError:
            raise
        except Exception as exc:
            log.error("  Unexpected error on %s: %s — skipping.", url, exc)

    if not results:
        log.error("No results. Check WordPress access and GSC data.")
        sys.exit(1)

    # ── Stage 2c: Keyword Planner + Bing (optional) ──────────────────────────
    planner_data: dict = {"enabled": False, "status": "skipped (demo)" if args.demo else ""}
    bing_data: dict = {"enabled": False, "status": "skipped"}

    if not args.demo and config.USE_KEYWORD_PLANNER:
        log.info("Stage 2c — Google Ads Keyword Planner (%s)", keyword_planner.status_message())
        seeds = gsc.seed_keywords_from_context(site_context, results)
        sample_url = (results[0].get("post") or {}).get("url") or results[0]["metrics"].get("page")
        planner_data = keyword_planner.enrich_for_briefing(seeds, sample_page_url=sample_url)
        log.info(
            "  planner ideas=%d historical=%d",
            len(planner_data.get("ideas") or []),
            len(planner_data.get("historical_for_seeds") or []),
        )
    elif not args.demo:
        planner_data = {
            "enabled": False,
            "status": "disabled (USE_KEYWORD_PLANNER=0)",
            "ideas": [],
            "historical_for_seeds": [],
        }

    if not args.demo and config.USE_BING:
        log.info("Stage 2d — Bing Webmaster (%s)", bing_webmaster.status_message())
        try:
            bing_data = bing_webmaster.get_site_context()
            log.info(
                "  bing queries=%d pages=%d",
                len(bing_data.get("queries") or []),
                len(bing_data.get("pages") or []),
            )
        except Exception as exc:
            log.warning("  Bing fetch failed: %s", exc)
            bing_data = {"enabled": False, "status": f"error: {exc}", "queries": [], "pages": []}

    # ── Stage 2e: PageSpeed ONLY on selected pages (after worst-N chosen) ───
    pagespeed_data: dict = {"enabled": False, "status": "skipped", "pages": {}}
    if not args.demo and config.USE_PAGESPEED:
        selected_urls = []
        for r in results:
            u = (r.get("post") or {}).get("url") or (r.get("metrics") or {}).get("page")
            if u and u not in selected_urls:
                selected_urls.append(u)
        log.info(
            "Stage 2e — PageSpeed on %d selected page(s) only (%s)",
            len(selected_urls),
            pagespeed.status_message(),
        )
        try:
            pagespeed_data = pagespeed.scan_selected_urls(selected_urls)
            log.info(
                "  PSI ok=%s/%s",
                pagespeed_data.get("ok_count"),
                pagespeed_data.get("scanned"),
            )
            # Attach per-result for convenience
            for r in results:
                u = (r.get("post") or {}).get("url") or (r.get("metrics") or {}).get("page")
                r["pagespeed"] = (pagespeed_data.get("pages") or {}).get(u)
        except Exception as exc:
            log.warning("  PageSpeed stage failed: %s", exc)
            pagespeed_data = {
                "enabled": False,
                "status": f"error: {exc}",
                "pages": {},
            }
    elif args.demo:
        pagespeed_data = {"enabled": False, "status": "skipped (demo)", "pages": {}}

    # ── Write handoff artifacts (you paste MD into Claude) ───────────────────
    payload = briefing.build_briefing_payload(
        results,
        site=config.GSC_SITE_URL,
        site_context=site_context,
        keyword_planner=planner_data,
        bing=bing_data,
        pagespeed=pagespeed_data,
    )
    _write_text(briefing_json, briefing.briefing_to_json(payload))
    _write_text(report_md, briefing.briefing_to_markdown(payload))
    report.build_report(results, output_path=str(report_html))

    # Report is on disk — now record cooldown state for the pages it covers.
    for state_url, state_metrics in pending_state:
        db.save_page_state(state_url, state_metrics, str(report_md))

    log.info("Done. %d page(s) written for Claude handoff:", len(results))
    log.info("  Markdown (paste into Claude): %s", report_md.resolve())
    log.info("  HTML (browser view):          %s", report_html.resolve())
    log.info("  JSON (optional):              %s", briefing_json.resolve())
    log.info(
        "Next: open the .md file → copy all → paste into Claude."
    )


if __name__ == "__main__":
    main()
