"""
Build the handoff report for manual Claude use (semi-automatic model).
"""
from __future__ import annotations

import json
from datetime import date
from typing import Any

import config

CLAUDE_HANDOFF_PROMPT = """\
You are a senior SEO editor for a health and wellness website (Eager to Be Healthy).

Pages were selected first (worst / most improvable), then enriched. PageSpeed was
run only on those selected URLs — not the whole site.

Sources:
1) Google Search Console — queries, trends, devices, countries, opportunities
2) Google Ads Keyword Planner — volume/competition when configured
3) Bing Webmaster — complementary engine data when configured
4) RankMath + WordPress content
5) PageSpeed Insights (lab) + CrUX field data when available

You will produce keyword strategy AND guidance for fresh HTML. Use PageSpeed so
rewrites fix real issues (LCP images, CLS, render-blocking, title/meta, headings,
alt text, tap targets) — not generic speed advice.

Posts are ordered RankMath improvable-first (under 20 → 40 → 60 → 80), then GSC
opportunity within a tier.

Using ONLY this briefing (do not invent metrics), produce:
- Executive summary: what to fix first and why
- Overview of selected posts
- Per post:
  - Primary + supporting keywords (grounded in GSC/Bing/Planner)
  - RankMath context; title / H1 / meta ideas; content gaps
  - HTML rewrite guidance from PageSpeed (prioritized for fresh markup)
  - Lab vs field (CrUX) notes when both exist
- Cannibalization notes
- Top 10 actions this week (improvable pages + HTML/CWV fixes first)

Do not invent search volume when Planner is missing.
Tone: practical, health/wellness-aware — suitable for shipping improved HTML.
"""


def _fmt_pct(v: float | None, digits: int = 1) -> str:
    if v is None:
        return "n/a"
    return f"{v * 100:.{digits}f}%"


def _fmt_delta(v: float | None, kind: str = "num") -> str:
    if v is None:
        return "n/a"
    if kind == "ratio":
        sign = "+" if v >= 0 else ""
        return f"{sign}{v * 100:.0f}%"
    sign = "+" if v >= 0 else ""
    if abs(v) >= 10:
        return f"{sign}{v:.0f}"
    return f"{sign}{v:.1f}"


def build_briefing_payload(
    results: list[dict],
    *,
    site: str,
    site_context: dict[str, Any] | None = None,
    keyword_planner: dict[str, Any] | None = None,
    bing: dict[str, Any] | None = None,
    pagespeed: dict[str, Any] | None = None,
) -> dict[str, Any]:
    posts = []
    for r in results:
        metrics = r["metrics"]
        post = r["post"]
        analysis = r.get("analysis") or {}
        queries = r.get("queries") or []
        posts.append({
            "title": post.get("title"),
            "url": post.get("url") or metrics.get("page"),
            "gsc": {
                "clicks": metrics.get("clicks"),
                "impressions": metrics.get("impressions"),
                "ctr": metrics.get("ctr"),
                "position": metrics.get("position"),
                "reasons": metrics.get("reasons") or [],
            },
            "rankmath_priority": {
                "seo_score": metrics.get("rankmath_score"),
                "tier": metrics.get("rankmath_tier"),
                "tier_label": metrics.get("rankmath_tier_label"),
                "focus_keyword": metrics.get("focus_keyword")
                or (post.get("rankmath") or {}).get("focus_keyword"),
            },
            "period_comparison": r.get("period_comparison") or {},
            "devices": r.get("devices") or [],
            "countries": r.get("countries") or [],
            "monthly_trend": r.get("monthly_trend") or [],
            "top_queries": [
                {
                    "query": q.get("query"),
                    "impressions": q.get("impressions"),
                    "clicks": q.get("clicks"),
                    "ctr": q.get("ctr"),
                    "position": q.get("position"),
                }
                for q in queries[:25]
            ],
            "rankmath": post.get("rankmath") or {},
            "pagespeed": r.get("pagespeed"),
            "local_keyword_recommendations": {
                "primary_keyword": analysis.get("primary_keyword"),
                "target_keywords": analysis.get("target_keywords") or [],
                "query_gaps": analysis.get("query_gaps") or [],
                "notes": analysis.get("notes") or analysis.get("summary") or "",
            }
            if analysis
            else None,
            "content_excerpt": (post.get("content_plain") or "")[:1500],
        })

    return {
        "site": site,
        "generated_on": date.today().isoformat(),
        "date_range_days": config.DATE_RANGE_DAYS,
        "post_count": len(posts),
        "local_model": config.local_llm_label(),
        "pipeline": [
            "1) Select worst/improvable pages (GSC + RankMath tiers)",
            "2) Enrich selected pages only (WP, GSC slices, Bing, Planner)",
            "3) PageSpeed scan selected pages only (lab + CrUX when available)",
            "4) Manual Claude handoff — keywords + fresh HTML guidance",
        ],
        "site_context": site_context or {},
        "keyword_planner": keyword_planner or {},
        "bing": bing or {},
        "pagespeed": pagespeed or {},
        "posts": posts,
        "data_limits": {
            "gsc": "Owned performance only — not market volume or SERP competitors",
            "keyword_planner": "Volume/competition when Ads API configured",
            "bing": "Bing-owned performance when API key set",
            "pagespeed": "Only selected URLs; lab Lighthouse + optional CrUX field data",
        },
    }


def briefing_to_markdown(briefing: dict[str, Any]) -> str:
    days = briefing.get("date_range_days")
    ctx = briefing.get("site_context") or {}
    dr = ctx.get("date_range") or {}
    cur = dr.get("current") or {}
    prev = dr.get("previous") or {}
    planner = briefing.get("keyword_planner") or {}
    bing = briefing.get("bing") or {}
    psi = briefing.get("pagespeed") or {}

    lines = [
        "# SEO Data Briefing — paste into Claude",
        "",
        f"**Site:** {briefing.get('site')}",
        f"**Generated:** {briefing.get('generated_on')}",
        f"**GSC window:** last {days} days"
        + (f" ({cur.get('start')} → {cur.get('end')})" if cur.get("start") else ""),
        f"**Compare vs prior:** {prev.get('start', '?')} → {prev.get('end', '?')}",
        f"**Keyword Planner:** {planner.get('status') or ('on' if planner.get('enabled') else 'off')}",
        f"**Bing:** {bing.get('status') or ('on' if bing.get('enabled') else 'off')}",
        f"**PageSpeed:** {psi.get('status') or ('on' if psi.get('enabled') else 'off')}"
        + (
            f" (scanned {psi.get('ok_count', 0)}/{psi.get('scanned', 0)} selected)"
            if psi.get("scanned") is not None
            else ""
        ),
        f"**Posts:** {briefing.get('post_count')} selected (worst / improvable first)",
        "",
        "## How to use",
        "1. Copy this entire file.",
        "2. Paste into Claude.",
        "3. Ask for keyword strategy **and** fresh HTML guidance using PageSpeed issues.",
        "",
        "### Selection order",
        "1. Identify worst/improvable pages (RankMath tiers + GSC).",
        "2. Enrich those pages only.",
        "3. **Then** PageSpeed-scan only the selected URLs (not the whole site).",
        "",
        "---",
        "",
        "## Claude prompt",
        "",
        "```",
        CLAUDE_HANDOFF_PROMPT.strip(),
        "```",
        "",
        "---",
        "",
        "## Site GSC — monthly trend",
        "",
    ]

    trend = ctx.get("monthly_trend") or []
    if trend:
        lines.append("| Month | Impr | Clicks | CTR | Pos |")
        lines.append("|-------|-----:|-------:|----:|----:|")
        for m in trend[-18:]:
            lines.append(
                f"| {m.get('month')} | {int(m.get('impressions') or 0)} | "
                f"{int(m.get('clicks') or 0)} | {float(m.get('ctr') or 0)*100:.2f}% | "
                f"{float(m.get('position') or 0):.1f} |"
            )
        lines.append("")
    else:
        lines.append("_No monthly trend rows._\n")

    lines.extend(["## Site GSC — devices & countries", ""])
    devs = ctx.get("devices") or []
    if devs:
        lines.append(
            "**Devices:** "
            + "; ".join(
                f"{d.get('device')}: {int(d.get('impressions') or 0)} impr / "
                f"{int(d.get('clicks') or 0)} clk / pos {float(d.get('position') or 0):.1f}"
                for d in devs
            )
        )
    countries = ctx.get("countries") or []
    if countries:
        lines.append(
            "**Countries:** "
            + "; ".join(
                f"{c.get('country')}: {int(c.get('impressions') or 0)} impr"
                for c in countries[:12]
            )
        )
    appearance = ctx.get("search_appearance") or []
    if appearance:
        lines.append(
            "**Search appearance:** "
            + "; ".join(
                f"{a.get('appearance')}: {int(a.get('impressions') or 0)} impr"
                for a in appearance[:12]
            )
        )
    else:
        lines.append("**Search appearance:** none / not reported")
    lines.append("")

    lines.extend(
        [
            "## Sitewide query opportunities (GSC)",
            "",
            "Demand with weak CTR/position — strong keyword candidates.",
            "",
        ]
    )
    opps = ctx.get("query_opportunities") or []
    if not opps:
        lines.append("_None returned._\n")
    else:
        lines.append("| Query | Impr | Clicks | CTR | Pos | Flags |")
        lines.append("|-------|-----:|-------:|----:|----:|-------|")
        for o in opps[:35]:
            q = str(o.get("query") or "").replace("|", "/")
            flags = ", ".join(o.get("flags") or [])
            lines.append(
                f"| {q} | {int(o.get('impressions') or 0)} | "
                f"{int(o.get('clicks') or 0)} | {float(o.get('ctr') or 0)*100:.2f}% | "
                f"{float(o.get('position') or 0):.1f} | {flags} |"
            )
        lines.append("")

    lines.extend(["## Top queries → best landing page (GSC)", ""])
    tqp = ctx.get("top_queries_with_pages") or []
    if not tqp:
        lines.append("_None._\n")
    else:
        for t in tqp[:25]:
            lines.append(
                f"- **“{t.get('query')}”** — {int(t.get('impressions') or 0)} impr, "
                f"{int(t.get('clicks') or 0)} clk → `{t.get('top_page')}` "
                f"(pos {float(t.get('top_page_position') or 0):.1f})"
            )
        lines.append("")

    lines.extend(
        [
            "## Query cannibalization (GSC)",
            "",
            "Same query on multiple URLs — consolidate or differentiate.",
            "",
        ]
    )
    cans = ctx.get("cannibalization") or []
    if not cans:
        lines.append("_No multi-URL overlaps in sample._\n")
    else:
        for c in cans[:20]:
            lines.append(
                f"- **“{c.get('query')}”** — {c.get('page_count')} pages, "
                f"{int(c.get('total_impressions') or 0)} impr"
            )
            for p in (c.get("pages") or [])[:4]:
                lines.append(
                    f"  - {p.get('page')} (impr={int(p.get('impressions') or 0)}, "
                    f"pos={float(p.get('position') or 0):.1f})"
                )
        lines.append("")

    # Keyword Planner
    lines.extend(["---", "", "## Google Ads Keyword Planner", ""])
    if planner.get("enabled"):
        lines.append(f"Status: **enabled** ({planner.get('status')})")
        seeds = planner.get("seed_keywords") or []
        if seeds:
            lines.append("**Seeds from GSC:** " + "; ".join(f"“{s}”" for s in seeds[:20]))
        hist = planner.get("historical_for_seeds") or []
        if hist:
            lines.append("")
            lines.append("### Volume for GSC seed keywords")
            lines.append("| Keyword | Monthly searches | Competition | Bid low–high USD |")
            lines.append("|---------|-----------------:|-------------|---------------:|")
            for h in hist[:40]:
                lines.append(
                    f"| {h.get('keyword')} | {int(h.get('avg_monthly_searches') or 0)} | "
                    f"{h.get('competition')} | "
                    f"{h.get('low_top_of_page_bid_usd') or '—'}–"
                    f"{h.get('high_top_of_page_bid_usd') or '—'} |"
                )
        ideas = planner.get("ideas") or []
        if ideas:
            lines.append("")
            lines.append("### Related keyword ideas (by volume)")
            lines.append("| Keyword | Monthly searches | Competition | Bid low–high USD |")
            lines.append("|---------|-----------------:|-------------|---------------:|")
            for h in ideas[:50]:
                lines.append(
                    f"| {h.get('keyword')} | {int(h.get('avg_monthly_searches') or 0)} | "
                    f"{h.get('competition')} | "
                    f"{h.get('low_top_of_page_bid_usd') or '—'}–"
                    f"{h.get('high_top_of_page_bid_usd') or '—'} |"
                )
        lines.append("")
    else:
        lines.append(f"Status: **not active** — {planner.get('status') or 'not configured'}")
        if planner.get("setup_hint"):
            lines.append(f"_{planner['setup_hint']}_")
        if planner.get("seed_keywords"):
            lines.append(
                "GSC seeds ready for Planner once Ads is configured: "
                + "; ".join(f"“{s}”" for s in (planner.get("seed_keywords") or [])[:15])
            )
        lines.append("")

    # Bing
    lines.extend(["---", "", "## Bing Webmaster (complementary)", ""])
    if bing.get("enabled"):
        lines.append(f"Status: **enabled** — {bing.get('status')}")
        bq = bing.get("queries") or []
        if bq:
            lines.append("")
            lines.append("### Bing top queries")
            lines.append("| Query | Impr | Clicks | Pos |")
            lines.append("|-------|-----:|-------:|----:|")
            for q in bq[:30]:
                lines.append(
                    f"| {str(q.get('query') or '').replace('|', '/')} | "
                    f"{int(q.get('impressions') or 0)} | {int(q.get('clicks') or 0)} | "
                    f"{float(q.get('position') or 0):.1f} |"
                )
        bp = bing.get("pages") or []
        if bp:
            lines.append("")
            lines.append("### Bing top pages")
            for p in bp[:20]:
                lines.append(
                    f"- {p.get('page')} — impr={int(p.get('impressions') or 0)}, "
                    f"clk={int(p.get('clicks') or 0)}, pos={float(p.get('position') or 0):.1f}"
                )
        for n in bing.get("notes") or []:
            lines.append(f"- _{n}_")
        lines.append("")
    else:
        lines.append(f"Status: **not active** — {bing.get('status') or 'not configured'}")
        lines.append(
            "_Optional: verify site in Bing Webmaster Tools, set BING_API_KEY + BING_SITE_URL._"
        )
        lines.append("")

    # Overview + posts
    lines.extend(
        [
            "---",
            "",
            "## Overview — improvable first (RankMath tiers, then GSC)",
            "",
            "| # | Title | RM score | Tier | Impr | Clicks | CTR | Pos | Why flagged |",
            "|---|-------|---------:|------|-----:|-------:|----:|----:|-------------|",
        ]
    )
    for i, p in enumerate(briefing.get("posts") or [], 1):
        g = p.get("gsc") or {}
        rp = p.get("rankmath_priority") or {}
        rm = p.get("rankmath") or {}
        score = rp.get("seo_score")
        if score is None:
            score = rm.get("seo_score")
        score_s = str(score) if score is not None else "—"
        tier = rp.get("tier_label") or "—"
        title = (p.get("title") or "Untitled").replace("|", "/")
        reasons = "; ".join(g.get("reasons") or []) or "—"
        lines.append(
            f"| {i} | {title[:50]} | {score_s} | {str(tier)[:22]} | "
            f"{int(g.get('impressions') or 0)} | "
            f"{int(g.get('clicks') or 0)} | {float(g.get('ctr') or 0)*100:.2f}% | "
            f"{float(g.get('position') or 0):.1f} | {reasons[:60]} |"
        )

    lines.extend(["", "---", "", "## Per-post briefing", ""])

    for i, p in enumerate(briefing.get("posts") or [], 1):
        g = p.get("gsc") or {}
        kw = p.get("local_keyword_recommendations") or {}
        period = p.get("period_comparison") or {}
        devices = p.get("devices") or []
        countries = p.get("countries") or []
        monthly = p.get("monthly_trend") or []

        rp = p.get("rankmath_priority") or {}
        rm = p.get("rankmath") or {}
        lines.append(f"### {i}. {p.get('title')}")
        lines.append(f"- **URL:** {p.get('url')}")
        score = rp.get("seo_score")
        if score is None:
            score = rm.get("seo_score")
        tier = rp.get("tier_label") or ""
        focus = rp.get("focus_keyword") or rm.get("focus_keyword") or "n/a"
        if score is not None:
            lines.append(
                f"- **RankMath:** score={score}/100"
                + (f" ({tier})" if tier else "")
                + f", focus_keyword={focus}"
            )
        elif rm or rp:
            lines.append(
                f"- **RankMath:** score unavailable, focus_keyword={focus}"
            )
        lines.append(
            f"- **GSC ({days}d):** impr={int(g.get('impressions') or 0)}, "
            f"clk={int(g.get('clicks') or 0)}, CTR={float(g.get('ctr') or 0)*100:.2f}%, "
            f"pos={float(g.get('position') or 0):.1f}"
        )
        if g.get("reasons"):
            lines.append("- **Flagged:** " + "; ".join(g["reasons"]))

        if period:
            cur_w = period.get("current_window") or {}
            prev_w = period.get("previous_window") or {}
            d = period.get("delta") or {}
            lines.append(
                f"- **Trend vs prior {days}d:** "
                f"impr {int(prev_w.get('impressions') or 0)}→{int(cur_w.get('impressions') or 0)} "
                f"({_fmt_delta(d.get('impressions_pct'), 'ratio')}), "
                f"clicks {int(prev_w.get('clicks') or 0)}→{int(cur_w.get('clicks') or 0)}, "
                f"pos {float(prev_w.get('position') or 0):.1f}→{float(cur_w.get('position') or 0):.1f}"
            )

        if devices:
            lines.append(
                "- **Devices:** "
                + "; ".join(
                    f"{d.get('device')}: {int(d.get('impressions') or 0)} impr / "
                    f"pos {float(d.get('position') or 0):.1f}"
                    for d in devices
                )
            )
        if countries:
            lines.append(
                "- **Countries:** "
                + "; ".join(
                    f"{c.get('country')}: {int(c.get('impressions') or 0)}"
                    for c in countries[:8]
                )
            )
        if monthly:
            recent = monthly[-6:]
            lines.append(
                "- **Monthly (recent):** "
                + "; ".join(
                    f"{m.get('month')}: {int(m.get('impressions') or 0)} impr"
                    for m in recent
                )
            )

        tq = p.get("top_queries") or []
        if tq:
            lines.append("- **Top GSC queries:**")
            for q in tq[:15]:
                lines.append(
                    f"  - “{q.get('query')}” — {int(q.get('impressions') or 0)} impr, "
                    f"{int(q.get('clicks') or 0)} clk, pos {float(q.get('position') or 0):.1f}, "
                    f"CTR {float(q.get('ctr') or 0)*100:.1f}%"
                )
        else:
            lines.append("- **Top GSC queries:** (none)")

        rm = p.get("rankmath") or {}
        if any(rm.values()):
            lines.append(
                f"- **RankMath:** focus={rm.get('focus_keyword') or 'n/a'}, "
                f"score={rm.get('seo_score') if rm.get('seo_score') is not None else 'n/a'}"
            )

        if kw:
            lines.append(
                f"- **Local LLM primary:** {kw.get('primary_keyword') or '(none)'}"
            )

        excerpt = (p.get("content_excerpt") or "").strip()
        # PageSpeed (selected pages only)
        ps = p.get("pagespeed") or {}
        if ps:
            if ps.get("ok"):
                lines.append("- **PageSpeed (selected-page scan):**")
                for strat, block in (ps.get("strategies") or {}).items():
                    scores = block.get("scores") or {}
                    lines.append(
                        f"  - **{strat}:** perf={scores.get('performance')}, "
                        f"a11y={scores.get('accessibility')}, "
                        f"bp={scores.get('best_practices')}, "
                        f"seo={scores.get('seo')}"
                    )
                    lab = (block.get("lab") or {}).get("core_metrics") or {}
                    bits = []
                    for mid in ("lcp", "cls", "tbt", "fcp"):
                        m = lab.get(mid) or {}
                        if m.get("display_value"):
                            bits.append(f"{mid.upper()} {m['display_value']}")
                    if bits:
                        lines.append(f"    Lab: {', '.join(bits)}")
                    field = block.get("field_crux") or {}
                    if field.get("overall_category") or field.get("metrics"):
                        lines.append(
                            f"    Field CrUX overall: {field.get('overall_category') or 'n/a'}"
                        )
                    issues = (block.get("lab") or {}).get("html_relevant_issues") or []
                    if issues:
                        lines.append("    HTML-relevant issues (for fresh markup):")
                        for iss in issues[:8]:
                            lines.append(
                                f"      - [{iss.get('id')}] {iss.get('title')}"
                                + (
                                    f" — {iss.get('display_value')}"
                                    if iss.get("display_value")
                                    else ""
                                )
                            )
            elif ps.get("error"):
                lines.append(f"- **PageSpeed:** failed — {ps.get('error')}")

        if excerpt:
            clip = excerpt[:700] + ("…" if len(excerpt) > 700 else "")
            lines.append(f"- **Excerpt:** > {clip}")
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append(
        "*End of automated briefing. Produce keyword strategy + fresh HTML guidance in Claude.*"
    )
    lines.append("")
    return "\n".join(lines)


def briefing_to_json(briefing: dict[str, Any]) -> str:
    return json.dumps(briefing, indent=2, ensure_ascii=False)
