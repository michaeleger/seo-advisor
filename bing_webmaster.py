"""
Bing Webmaster Tools — free complementary search data for Claude handoffs.

Official JSON API (GET, siteUrl + apikey only):
  https://ssl.bing.com/webmaster/api.svc/json/GetQueryStats?siteUrl=...&apikey=...
  https://ssl.bing.com/webmaster/api.svc/json/GetPageStats?siteUrl=...&apikey=...

Rows are daily; we aggregate by query/page. Data updates about weekly.

Setup:
  python setup_bing.py YOUR_API_KEY
  # or set BING_API_KEY in .env
"""
from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any

import requests

import config

log = logging.getLogger(__name__)

_BASE = "https://ssl.bing.com/webmaster/api.svc/json"


def is_configured() -> bool:
    return bool(config.BING_API_KEY and config.BING_SITE_URL)


def status_message() -> str:
    if is_configured():
        return f"configured ({config.BING_SITE_URL})"
    return "not configured — run: python setup_bing.py YOUR_API_KEY"


def _get(method: str, *, site_url: str | None = None) -> Any:
    site = site_url or config.BING_SITE_URL
    params = {
        "apikey": config.BING_API_KEY,
        "siteUrl": site,
    }
    url = f"{_BASE}/{method}"
    resp = requests.get(
        url,
        params=params,
        timeout=60,
        headers={"Accept": "application/json"},
    )
    if resp.status_code >= 400:
        # Include body for easier debugging (API key / site URL issues)
        raise RuntimeError(
            f"Bing {method} HTTP {resp.status_code}: {resp.text[:400]}"
        )
    data = resp.json()
    if isinstance(data, dict) and "d" in data:
        return data["d"]
    return data


def _aggregate_query_stats(rows: list) -> list[dict]:
    """
    Bing returns daily QueryStats rows:
      Query, Clicks, Impressions, AvgClickPosition, AvgImpressionPosition, Date
    Aggregate to one row per Query (or page URL when method is GetPageStats).
    """
    by_key: dict[str, dict[str, float]] = defaultdict(
        lambda: {
            "clicks": 0.0,
            "impressions": 0.0,
            "pos_weight": 0.0,
            "days": 0.0,
        }
    )
    for r in rows:
        if not isinstance(r, dict):
            continue
        key = (r.get("Query") or r.get("query") or "").strip()
        if not key:
            continue
        clicks = float(r.get("Clicks") or r.get("clicks") or 0)
        impr = float(r.get("Impressions") or r.get("impressions") or 0)
        pos = float(
            r.get("AvgImpressionPosition")
            or r.get("AvgClickPosition")
            or r.get("position")
            or 0
        )
        m = by_key[key]
        m["clicks"] += clicks
        m["impressions"] += impr
        m["pos_weight"] += pos * impr if impr else 0.0
        m["days"] += 1

    out: list[dict] = []
    for key, m in by_key.items():
        impr = m["impressions"]
        out.append(
            {
                "key": key,
                "clicks": int(m["clicks"]),
                "impressions": int(impr),
                "ctr": (m["clicks"] / impr) if impr else 0.0,
                "position": (m["pos_weight"] / impr) if impr else 0.0,
                "days_with_data": int(m["days"]),
            }
        )
    out.sort(key=lambda x: x["impressions"], reverse=True)
    return out


def get_query_stats(limit: int = 50) -> list[dict]:
    """Top queries on Bing for the site (aggregated across Bing's returned days)."""
    if not is_configured():
        return []
    data = _get("GetQueryStats")
    rows = data if isinstance(data, list) else []
    agg = _aggregate_query_stats(rows)
    return [
        {
            "query": a["key"],
            "clicks": a["clicks"],
            "impressions": a["impressions"],
            "ctr": a["ctr"],
            "position": a["position"],
            "days_with_data": a["days_with_data"],
        }
        for a in agg[:limit]
    ]


def get_page_stats(limit: int = 50) -> list[dict]:
    """Top pages on Bing (Query field holds the page URL)."""
    if not is_configured():
        return []
    data = _get("GetPageStats")
    rows = data if isinstance(data, list) else []
    agg = _aggregate_query_stats(rows)
    return [
        {
            "page": a["key"],
            "clicks": a["clicks"],
            "impressions": a["impressions"],
            "ctr": a["ctr"],
            "position": a["position"],
            "days_with_data": a["days_with_data"],
        }
        for a in agg[:limit]
    ]


def get_rank_and_traffic() -> dict[str, Any] | None:
    """Site-level rank/traffic summary if available."""
    if not is_configured():
        return None
    try:
        data = _get("GetRankAndTrafficStats")
    except Exception as exc:
        log.debug("GetRankAndTrafficStats unavailable: %s", exc)
        return None
    if isinstance(data, list) and data:
        # list of daily points — sum recent
        clicks = sum(float(r.get("Clicks") or 0) for r in data if isinstance(r, dict))
        impr = sum(float(r.get("Impressions") or 0) for r in data if isinstance(r, dict))
        return {
            "days": len(data),
            "clicks": int(clicks),
            "impressions": int(impr),
        }
    if isinstance(data, dict):
        return data
    return None


def test_connection() -> tuple[bool, str]:
    """Return (ok, message) for setup_bing.py."""
    if not is_configured():
        return False, status_message()
    try:
        data = _get("GetQueryStats")
        n = len(data) if isinstance(data, list) else 0
        return True, f"OK — GetQueryStats returned {n} raw row(s) for {config.BING_SITE_URL}"
    except Exception as exc:
        return False, str(exc)


def get_site_context() -> dict[str, Any]:
    if not is_configured():
        return {
            "enabled": False,
            "status": status_message(),
            "queries": [],
            "pages": [],
            "traffic": None,
            "notes": [
                "Bing is free. Verify site at https://www.bing.com/webmasters , "
                "copy API key, run: python setup_bing.py YOUR_API_KEY",
            ],
        }

    try:
        queries = get_query_stats()
        pages = get_page_stats()
        traffic = get_rank_and_traffic()
    except Exception as exc:
        log.warning("Bing fetch failed: %s", exc)
        return {
            "enabled": False,
            "status": f"error: {exc}",
            "queries": [],
            "pages": [],
            "traffic": None,
            "notes": [
                "Check BING_API_KEY and that BING_SITE_URL matches the verified site "
                "exactly (often https://www.example.com/ with trailing slash).",
            ],
        }

    log.info("Bing: %d queries, %d pages (free API)", len(queries), len(pages))
    return {
        "enabled": True,
        "status": status_message(),
        "site_url": config.BING_SITE_URL,
        "queries": queries,
        "pages": pages,
        "traffic": traffic,
        "notes": [
            "Bing data is free and complementary to Google Search Console.",
            "Query mix often differs from Google — use for extra keyword angles.",
            "Volume is usually lower than Google for US health sites.",
            "Data typically refreshes about weekly.",
        ],
    }
