"""
PageSpeed Insights + Chrome UX Report field data — only for selected URLs.

Pipeline order (by design):
  1) Identify worst / most improvable pages (GSC + RankMath + …)
  2) Scan ONLY those pages here (not the whole site)

Free Google API: https://developers.google.com/speed/docs/insights/v5/get-started
Set PAGESPEED_API_KEY in .env (Google Cloud → enable PageSpeed Insights API → API key).
Without a key, anonymous quota is tiny; with a key, free daily quota is usually enough
for ~10 URLs × mobile+desktop.
"""
from __future__ import annotations

import logging
import time
from typing import Any

import requests

import config

log = logging.getLogger(__name__)

_API = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"


def is_configured() -> bool:
    return bool(getattr(config, "USE_PAGESPEED", True))


def status_message() -> str:
    if not getattr(config, "USE_PAGESPEED", True):
        return "disabled (USE_PAGESPEED=0)"
    key = getattr(config, "PAGESPEED_API_KEY", "") or ""
    if key:
        return "enabled (API key set)"
    return "enabled (no API key — anonymous quota; set PAGESPEED_API_KEY for reliability)"


def _category_scores(lighthouse: dict) -> dict[str, int | None]:
    cats = lighthouse.get("categories") or {}
    out: dict[str, int | None] = {}
    for key, label in (
        ("performance", "performance"),
        ("accessibility", "accessibility"),
        ("best-practices", "best_practices"),
        ("seo", "seo"),
    ):
        block = cats.get(key) or {}
        score = block.get("score")
        out[label] = int(round(score * 100)) if score is not None else None
    return out


def _audits_snapshot(lighthouse: dict) -> dict[str, Any]:
    """Core metrics + a few HTML-relevant audits for Claude rewrites."""
    audits = lighthouse.get("audits") or {}

    def metric(audit_id: str) -> dict[str, Any] | None:
        a = audits.get(audit_id) or {}
        if not a:
            return None
        return {
            "id": audit_id,
            "title": a.get("title"),
            "display_value": a.get("displayValue"),
            "score": a.get("score"),
            "numeric_value": a.get("numericValue"),
        }

    core = {
        "fcp": metric("first-contentful-paint"),
        "lcp": metric("largest-contentful-paint"),
        "cls": metric("cumulative-layout-shift"),
        "tbt": metric("total-blocking-time"),
        "si": metric("speed-index"),
        "tti": metric("interactive"),
    }

    # Audits that matter when Claude produces fresh HTML
    html_relevant_ids = [
        "document-title",
        "meta-description",
        "heading-order",
        "image-alt",
        "link-name",
        "crawlable-anchors",
        "is-crawlable",
        "robots-txt",
        "hreflang",
        "canonical",
        "viewport",
        "font-size",
        "tap-targets",
        "structured-data",  # may not always exist
        "unsized-images",
        "render-blocking-resources",
        "unused-css-rules",
        "unused-javascript",
        "modern-image-formats",
        "uses-responsive-images",
        "server-response-time",
    ]
    issues: list[dict] = []
    for aid in html_relevant_ids:
        a = audits.get(aid)
        if not a:
            continue
        score = a.get("score")
        # 1 = pass, null = informative, <1 = opportunity/fail
        if score is not None and score >= 0.9:
            continue
        if score is None and not a.get("details"):
            continue
        issues.append(
            {
                "id": aid,
                "title": a.get("title"),
                "description": (a.get("description") or "")[:280],
                "display_value": a.get("displayValue"),
                "score": score,
            }
        )
    # Worst first (lowest score)
    issues.sort(key=lambda x: (x["score"] is None, x["score"] if x["score"] is not None else 99))
    return {"core_metrics": core, "html_relevant_issues": issues[:15]}


def _field_data(block: dict | None) -> dict[str, Any] | None:
    """Chrome UX Report field data when available."""
    if not block:
        return None
    metrics = block.get("metrics") or {}
    overall = block.get("overall_category")
    out: dict[str, Any] = {"overall_category": overall, "metrics": {}}
    for key, label in (
        ("LARGEST_CONTENTFUL_PAINT_MS", "lcp"),
        ("CUMULATIVE_LAYOUT_SHIFT_SCORE", "cls"),
        ("INTERACTION_TO_NEXT_PAINT", "inp"),
        ("FIRST_CONTENTFUL_PAINT_MS", "fcp"),
        ("EXPERIMENTAL_TIME_TO_FIRST_BYTE", "ttfb"),
    ):
        m = metrics.get(key)
        if not m:
            continue
        out["metrics"][label] = {
            "percentile": m.get("percentile"),
            "category": m.get("category"),
        }
    return out if out["metrics"] or overall else None


def run_strategy(url: str, strategy: str) -> dict[str, Any]:
    """
    strategy: 'mobile' | 'desktop'
    """
    params: list[tuple[str, str]] = [
        ("url", url),
        ("strategy", strategy),
        ("category", "performance"),
        ("category", "accessibility"),
        ("category", "best-practices"),
        ("category", "seo"),
    ]
    key = getattr(config, "PAGESPEED_API_KEY", "") or ""
    if key:
        params.append(("key", key))

    timeout = int(getattr(config, "PAGESPEED_TIMEOUT_SECONDS", 120))
    resp = requests.get(_API, params=params, timeout=timeout)
    if resp.status_code != 200:
        raise RuntimeError(f"PSI HTTP {resp.status_code}: {resp.text[:300]}")
    data = resp.json()
    if data.get("error"):
        err = data["error"]
        raise RuntimeError(err.get("message") or str(err))

    lighthouse = data.get("lighthouseResult") or {}
    scores = _category_scores(lighthouse)
    snap = _audits_snapshot(lighthouse)
    return {
        "strategy": strategy,
        "final_url": (lighthouse.get("finalUrl") or data.get("id") or url),
        "fetch_time": lighthouse.get("fetchTime"),
        "scores": scores,
        "lab": snap,
        "field_crux": _field_data(data.get("loadingExperience")),
        "origin_crux": _field_data(data.get("originLoadingExperience")),
    }


def analyze_url(url: str) -> dict[str, Any]:
    """Run mobile (+ optional desktop) for one selected URL."""
    strategies = getattr(config, "PAGESPEED_STRATEGIES", ["mobile"]) or ["mobile"]
    strategies = [s.strip().lower() for s in strategies if s.strip()]
    if not strategies:
        strategies = ["mobile"]

    out: dict[str, Any] = {
        "url": url,
        "ok": False,
        "strategies": {},
        "error": None,
    }
    errors: list[str] = []
    for i, strategy in enumerate(strategies):
        if i:
            # gentle pacing for free quota
            time.sleep(float(getattr(config, "PAGESPEED_PAUSE_SECONDS", 1.5)))
        try:
            out["strategies"][strategy] = run_strategy(url, strategy)
            out["ok"] = True
        except Exception as exc:
            log.warning("PageSpeed %s failed for %s: %s", strategy, url, exc)
            errors.append(f"{strategy}: {exc}")
    if errors:
        out["error"] = "; ".join(errors)
    return out


def scan_selected_urls(urls: list[str]) -> dict[str, Any]:
    """
    Page-scan ONLY the already-selected worst pages.
    Returns a briefing-ready bundle keyed by URL.
    """
    if not getattr(config, "USE_PAGESPEED", True):
        return {
            "enabled": False,
            "status": status_message(),
            "pages": {},
            "notes": ["PageSpeed disabled."],
        }

    pages: dict[str, dict] = {}
    log.info(
        "PageSpeed: scanning %d selected URL(s) only (%s)",
        len(urls),
        status_message(),
    )
    for i, url in enumerate(urls, 1):
        log.info("  PSI [%d/%d] %s", i, len(urls), url)
        pages[url] = analyze_url(url)
        if i < len(urls):
            time.sleep(float(getattr(config, "PAGESPEED_PAUSE_SECONDS", 1.5)))

    ok_n = sum(1 for p in pages.values() if p.get("ok"))
    return {
        "enabled": True,
        "status": status_message(),
        "scanned": len(urls),
        "ok_count": ok_n,
        "pages": pages,
        "notes": [
            "Scanned only the selected worst/improvable pages (not the whole site).",
            "Lab = Lighthouse on a simulated device; Field = Chrome UX Report when enough real-user data.",
            "Use scores + html_relevant_issues when Claude produces fresh HTML "
            "(images, CLS, render-blocking, title/meta, headings, a11y).",
        ],
    }
