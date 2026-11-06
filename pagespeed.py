"""
PageSpeed Insights + Chrome UX Report field data — only for selected URLs.

Pipeline order (by design):
  1) Identify worst / most improvable pages (GSC + RankMath + …)
  2) Scan ONLY those pages here (not the whole site)

Free Google API: https://developers.google.com/speed/docs/insights/v5/get-started
Set PAGESPEED_API_KEY in .env (Google Cloud → enable PageSpeed Insights API → API key).
The key is required: anonymous PSI quota is small enough that the 2026-09-10 run
got HTTP 429 on every URL. With a key the free daily quota covers ~10 URLs ×
mobile+desktop, so a missing key skips the stage rather than burning the run.

Nothing here puts a response body into its errors. PSI 429/403 bodies name the
calling project number, and `requests` puts the full request URL — including
`?key=` — into its own exception messages; both end up in a Markdown briefing
that gets pasted elsewhere. Errors are collapsed to a status line instead.
"""
from __future__ import annotations

import logging
import time
from typing import Any

import requests

import config

log = logging.getLogger(__name__)

_API = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"

# What each status code means, in words that carry no request or response detail.
_HTTP_REASONS = {
    400: "request rejected",
    403: "forbidden — check the API key and that the PSI API is enabled",
    404: "PSI could not fetch the page",
    429: "rate limited — PSI quota exhausted",
    500: "PSI server error",
    503: "PSI temporarily unavailable",
}


class PageSpeedError(RuntimeError):
    """A PSI failure carrying only a message that is safe to print in a report."""

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        rate_limited: bool = False,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.rate_limited = rate_limited


def _http_error(status: int) -> PageSpeedError:
    reason = _HTTP_REASONS.get(status, "unexpected response")
    return PageSpeedError(
        f"HTTP {status} — {reason}",
        status=status,
        rate_limited=status == 429,
    )


def _api_key() -> str:
    return (getattr(config, "PAGESPEED_API_KEY", "") or "").strip()


def is_configured() -> bool:
    """True only when the stage can actually run: enabled *and* keyed."""
    if not getattr(config, "USE_PAGESPEED", True):
        return False
    return bool(_api_key())


def status_message() -> str:
    if not getattr(config, "USE_PAGESPEED", True):
        return "disabled (USE_PAGESPEED=0)"
    if not _api_key():
        return (
            "skipped — PAGESPEED_API_KEY not set "
            "(anonymous PSI is rate-limited to failure; set a key in .env)"
        )
    return "enabled (API key set)"


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
    key = _api_key()
    if key:
        params.append(("key", key))

    timeout = int(getattr(config, "PAGESPEED_TIMEOUT_SECONDS", 120))
    resp = requests.get(_API, params=params, timeout=timeout)
    if resp.status_code != 200:
        # Deliberately not resp.text: 429/403 bodies name the project number.
        raise _http_error(resp.status_code)
    try:
        data = resp.json()
    except Exception:
        raise PageSpeedError("PSI returned a non-JSON response") from None
    if data.get("error"):
        # Same reasoning — the error message itself is Google-authored text
        # about our project, so only its code crosses into the report.
        try:
            code = int((data["error"] or {}).get("code") or 0)
        except (TypeError, ValueError):
            code = 0
        if code:
            raise _http_error(code)
        raise PageSpeedError("PSI reported an error")

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
        "rate_limited": False,
    }
    errors: list[str] = []
    for i, strategy in enumerate(strategies):
        if i:
            # gentle pacing for free quota
            time.sleep(float(getattr(config, "PAGESPEED_PAUSE_SECONDS", 1.5)))
        try:
            out["strategies"][strategy] = run_strategy(url, strategy)
            out["ok"] = True
        except PageSpeedError as exc:
            log.warning("PageSpeed %s failed for %s: %s", strategy, url, exc)
            errors.append(f"{strategy}: {exc}")
            if exc.rate_limited:
                # The second strategy would hit the same wall.
                out["rate_limited"] = True
                break
        except Exception as exc:
            # `requests` exception text includes the request URL, and the
            # request URL includes the API key. Only the class name is safe.
            log.warning(
                "PageSpeed %s failed for %s: %s", strategy, url, type(exc).__name__
            )
            log.debug("PageSpeed failure detail", exc_info=True)
            errors.append(f"{strategy}: request failed ({type(exc).__name__})")
    if errors:
        out["error"] = "; ".join(errors)
    return out


def scan_selected_urls(urls: list[str]) -> dict[str, Any]:
    """
    Page-scan ONLY the already-selected worst pages.
    Returns a briefing-ready bundle keyed by URL.
    """
    if not is_configured():
        status = status_message()
        log.info("PageSpeed: %s — stage skipped, no URLs scanned.", status)
        return {
            "enabled": False,
            "status": status,
            "requested": len(urls),
            "scanned": 0,
            "ok_count": 0,
            "pages": {},
            "notes": [f"PageSpeed not run: {status}"],
        }

    pages: dict[str, dict] = {}
    stopped_early = False
    log.info(
        "PageSpeed: scanning %d selected URL(s) only (%s)",
        len(urls),
        status_message(),
    )
    for i, url in enumerate(urls, 1):
        log.info("  PSI [%d/%d] %s", i, len(urls), url)
        result = analyze_url(url)
        pages[url] = result
        if result.get("rate_limited"):
            # One 429 means the quota is gone; the remaining URLs would each
            # cost a request to learn the same thing.
            stopped_early = True
            log.warning(
                "PageSpeed: HTTP 429 from PSI — stopping after %d of %d URL(s); "
                "the rest are not scanned this run.",
                i,
                len(urls),
            )
            break
        if i < len(urls):
            time.sleep(float(getattr(config, "PAGESPEED_PAUSE_SECONDS", 1.5)))

    ok_n = sum(1 for p in pages.values() if p.get("ok"))
    status = status_message()
    if stopped_early:
        status = f"{status} — stopped early after HTTP 429 (rate limit)"
    notes = []
    if stopped_early:
        notes.append(
            f"Stopped after {len(pages)} of {len(urls)} selected URL(s): PSI "
            "returned HTTP 429 (rate limit). The remaining pages were not scanned."
        )
    return {
        "enabled": True,
        "status": status,
        "requested": len(urls),
        "scanned": len(pages),
        "ok_count": ok_n,
        "stopped_early": stopped_early,
        "pages": pages,
        "notes": notes + [
            "Scanned only the selected worst/improvable pages (not the whole site).",
            "Lab = Lighthouse on a simulated device; Field = Chrome UX Report when enough real-user data.",
            "Use scores + html_relevant_issues when Claude produces fresh HTML "
            "(images, CLS, render-blocking, title/meta, headings, a11y).",
        ],
    }
