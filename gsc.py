"""Google Search Console API — full useful extract for Claude handoff."""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date, timedelta
import os
from typing import Any

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

import config

log = logging.getLogger(__name__)

_SCOPES = ["https://www.googleapis.com/auth/webmasters.readonly"]
_TOKEN_FILE = "token.json"
_service = None


def _get_credentials() -> Credentials:
    if not os.path.exists(_TOKEN_FILE):
        raise FileNotFoundError(
            "token.json not found. Run `python authorize.py` first "
            "(from an RDP desktop session on 5by5)."
        )
    creds = Credentials.from_authorized_user_file(_TOKEN_FILE, _SCOPES)
    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except Exception as exc:
            raise RuntimeError(
                "Google OAuth token refresh failed (invalid_grant or revoked). "
                "Re-run `python authorize.py` on 5by5 (RDP desktop) to recreate token.json. "
                f"Original error: {exc}"
            ) from exc
        with open(_TOKEN_FILE, "w") as f:
            f.write(creds.to_json())
    if not creds.valid:
        raise RuntimeError(
            "Google OAuth credentials are not valid. Run `python authorize.py` "
            "on 5by5 (RDP desktop) to re-authenticate Search Console access."
        )
    return creds


def _get_service():
    global _service
    if _service is None:
        _service = build(
            "searchconsole", "v1", credentials=_get_credentials(), cache_discovery=False
        )
    return _service


def _date_range() -> tuple[str, str]:
    end = date.today() - timedelta(days=3)
    start = end - timedelta(days=config.DATE_RANGE_DAYS)
    return start.isoformat(), end.isoformat()


def _prior_date_range() -> tuple[str, str]:
    end = date.today() - timedelta(days=3) - timedelta(days=config.DATE_RANGE_DAYS)
    start = end - timedelta(days=config.DATE_RANGE_DAYS)
    return start.isoformat(), end.isoformat()


def _query(body: dict[str, Any]) -> list[dict]:
    resp = (
        _get_service()
        .searchanalytics()
        .query(siteUrl=config.GSC_SITE_URL, body=body)
        .execute()
    )
    return resp.get("rows") or []


# Search Console returns at most 25 000 rows per request and pages via
# startRow. A single capped request silently truncates on any site with real
# traffic, and the loss is invisible — you just get a partial picture.
_API_MAX_ROWS = 25_000
# Safety valve so a huge property cannot spin here indefinitely.
_MAX_PAGES = 40


def _query_all(
    body: dict[str, Any],
    *,
    max_rows: int | None = None,
    label: str = "query",
) -> list[dict]:
    """
    Page through searchanalytics until the result set is exhausted.

    Truncation is logged rather than silent: if we stop early, the caller and
    the operator both find out.
    """
    page_size = min(int(body.get("rowLimit") or _API_MAX_ROWS), _API_MAX_ROWS)
    if max_rows is not None:
        page_size = min(page_size, max_rows)

    out: list[dict] = []
    start = 0
    for _ in range(_MAX_PAGES):
        rows = _query({**body, "rowLimit": page_size, "startRow": start})
        out.extend(rows)
        if len(rows) < page_size:
            return out
        if max_rows is not None and len(out) >= max_rows:
            log.debug("%s: reached max_rows=%d", label, max_rows)
            return out[:max_rows]
        start += len(rows)
    log.warning(
        "%s: stopped at the %d-request safety cap (%d rows); results are "
        "truncated. Narrow DATE_RANGE_DAYS if this matters.",
        label,
        _MAX_PAGES,
        len(out),
    )
    return out


def _row_metrics(r: dict) -> dict:
    return {
        "clicks": r.get("clicks", 0),
        "impressions": r.get("impressions", 0),
        "ctr": r.get("ctr", 0.0),
        "position": r.get("position", 0.0),
    }


def _page_filter(page_url: str) -> list[dict]:
    return [
        {
            "filters": [
                {
                    "dimension": "page",
                    "operator": "equals",
                    "expression": page_url,
                }
            ]
        }
    ]


def get_page_metrics() -> list[dict]:
    start, end = _date_range()
    rows = _query_all(
        {
            "startDate": start,
            "endDate": end,
            "dimensions": ["page"],
            "rowLimit": _API_MAX_ROWS,
            "dataState": "final",
        },
        label="page metrics",
    )
    return [{"page": r["keys"][0], **_row_metrics(r)} for r in rows]


def get_page_queries(page_url: str, limit: int = 50) -> list[dict]:
    start, end = _date_range()
    rows = _query(
        {
            "startDate": start,
            "endDate": end,
            "dimensions": ["query"],
            "dimensionFilterGroups": _page_filter(page_url),
            "rowLimit": limit,
            "dataState": "final",
        }
    )
    out = [{"query": r["keys"][0], **_row_metrics(r)} for r in rows]
    out.sort(key=lambda x: x["impressions"], reverse=True)
    return out


def get_page_period_comparison(page_url: str) -> dict[str, Any]:
    cur_start, cur_end = _date_range()
    prev_start, prev_end = _prior_date_range()

    def _one(start: str, end: str) -> dict:
        rows = _query(
            {
                "startDate": start,
                "endDate": end,
                "dimensions": ["page"],
                "dimensionFilterGroups": _page_filter(page_url),
                "rowLimit": 1,
                "dataState": "final",
            }
        )
        if not rows:
            return {"clicks": 0, "impressions": 0, "ctr": 0.0, "position": 0.0}
        return _row_metrics(rows[0])

    current = _one(cur_start, cur_end)
    previous = _one(prev_start, prev_end)

    def _pct_change(cur: float, prev: float) -> float | None:
        if prev == 0:
            return None
        return (cur - prev) / prev

    return {
        "current_window": {"start": cur_start, "end": cur_end, **current},
        "previous_window": {"start": prev_start, "end": prev_end, **previous},
        "delta": {
            "clicks": current["clicks"] - previous["clicks"],
            "impressions": current["impressions"] - previous["impressions"],
            "ctr": current["ctr"] - previous["ctr"],
            "position": current["position"] - previous["position"],
            "impressions_pct": _pct_change(
                current["impressions"], previous["impressions"]
            ),
            "clicks_pct": _pct_change(current["clicks"], previous["clicks"]),
        },
    }


def get_page_devices(page_url: str) -> list[dict]:
    start, end = _date_range()
    rows = _query(
        {
            "startDate": start,
            "endDate": end,
            "dimensions": ["device"],
            "dimensionFilterGroups": _page_filter(page_url),
            "rowLimit": 10,
            "dataState": "final",
        }
    )
    out = [{"device": r["keys"][0], **_row_metrics(r)} for r in rows]
    out.sort(key=lambda x: x["impressions"], reverse=True)
    return out


def get_page_countries(page_url: str, limit: int = 10) -> list[dict]:
    start, end = _date_range()
    rows = _query(
        {
            "startDate": start,
            "endDate": end,
            "dimensions": ["country"],
            "dimensionFilterGroups": _page_filter(page_url),
            "rowLimit": limit,
            "dataState": "final",
        }
    )
    out = [{"country": r["keys"][0].upper(), **_row_metrics(r)} for r in rows]
    out.sort(key=lambda x: x["impressions"], reverse=True)
    return out


def get_page_monthly_trend(page_url: str) -> list[dict]:
    """Monthly rollup for one page (from daily GSC rows)."""
    start, end = _date_range()
    rows = _query(
        {
            "startDate": start,
            "endDate": end,
            "dimensions": ["date"],
            "dimensionFilterGroups": _page_filter(page_url),
            "rowLimit": 25000,
            "dataState": "final",
        }
    )
    by_month: dict[str, dict[str, float]] = defaultdict(
        lambda: {"clicks": 0.0, "impressions": 0.0, "pos_weight": 0.0}
    )
    for r in rows:
        day = r["keys"][0]  # YYYY-MM-DD
        month = day[:7]
        m = by_month[month]
        impr = float(r.get("impressions") or 0)
        m["clicks"] += float(r.get("clicks") or 0)
        m["impressions"] += impr
        m["pos_weight"] += float(r.get("position") or 0) * impr

    out = []
    for month in sorted(by_month.keys()):
        m = by_month[month]
        impr = m["impressions"]
        out.append(
            {
                "month": month,
                "clicks": int(m["clicks"]),
                "impressions": int(impr),
                "ctr": (m["clicks"] / impr) if impr else 0.0,
                "position": (m["pos_weight"] / impr) if impr else 0.0,
            }
        )
    return out


def get_site_query_opportunities(limit: int = 50) -> list[dict]:
    start, end = _date_range()
    rows = _query_all(
        {
            "startDate": start,
            "endDate": end,
            "dimensions": ["query"],
            "rowLimit": _API_MAX_ROWS,
            "dataState": "final",
        },
        label="site query opportunities",
    )
    min_impr = max(2, config.MIN_IMPRESSIONS)
    scored: list[dict] = []
    for r in rows:
        m = _row_metrics(r)
        if m["impressions"] < min_impr:
            continue
        flags: list[str] = []
        pos = m["position"]
        if 4.0 <= pos <= 20.0:
            flags.append("striking_distance")
        elif pos > 20.0:
            flags.append("deep_results")
        if m["ctr"] < config.MAX_CTR:
            flags.append("low_ctr")
        if m["clicks"] == 0:
            flags.append("zero_clicks")
        if not flags:
            continue
        score = m["impressions"] * (1.0 - m["ctr"]) * max(pos, 1.0)
        scored.append(
            {
                "query": r["keys"][0],
                **m,
                "flags": flags,
                "opportunity_score": score,
            }
        )
    scored.sort(key=lambda x: x["opportunity_score"], reverse=True)
    return scored[:limit]


def get_query_cannibalization(limit_queries: int = 40) -> list[dict]:
    start, end = _date_range()
    rows = _query_all(
        {
            "startDate": start,
            "endDate": end,
            "dimensions": ["query", "page"],
            "rowLimit": _API_MAX_ROWS,
            "dataState": "final",
        },
        label="cannibalization",
    )
    by_query: dict[str, list[dict]] = {}
    for r in rows:
        q, page = r["keys"][0], r["keys"][1]
        by_query.setdefault(q, []).append({"page": page, **_row_metrics(r)})

    conflicts: list[dict] = []
    for query, pages in by_query.items():
        if len(pages) < 2:
            continue
        pages.sort(key=lambda x: x["impressions"], reverse=True)
        total_impr = sum(p["impressions"] for p in pages)
        if total_impr < max(2, config.MIN_IMPRESSIONS):
            continue
        conflicts.append(
            {
                "query": query,
                "page_count": len(pages),
                "total_impressions": total_impr,
                "pages": pages[:6],
            }
        )
    conflicts.sort(key=lambda x: x["total_impressions"], reverse=True)
    return conflicts[:limit_queries]


def get_site_countries(limit: int = 15) -> list[dict]:
    start, end = _date_range()
    rows = _query(
        {
            "startDate": start,
            "endDate": end,
            "dimensions": ["country"],
            "rowLimit": limit,
            "dataState": "final",
        }
    )
    out = [{"country": r["keys"][0].upper(), **_row_metrics(r)} for r in rows]
    out.sort(key=lambda x: x["impressions"], reverse=True)
    return out


def get_site_devices() -> list[dict]:
    start, end = _date_range()
    rows = _query(
        {
            "startDate": start,
            "endDate": end,
            "dimensions": ["device"],
            "rowLimit": 10,
            "dataState": "final",
        }
    )
    out = [{"device": r["keys"][0], **_row_metrics(r)} for r in rows]
    out.sort(key=lambda x: x["impressions"], reverse=True)
    return out


def get_search_appearance(limit: int = 25) -> list[dict]:
    """Rich-result / search appearance types (FAQ, how-to, etc. if any)."""
    start, end = _date_range()
    try:
        rows = _query(
            {
                "startDate": start,
                "endDate": end,
                "dimensions": ["searchAppearance"],
                "rowLimit": limit,
                "dataState": "final",
            }
        )
    except Exception:
        return []
    out = [{"appearance": r["keys"][0], **_row_metrics(r)} for r in rows]
    out.sort(key=lambda x: x["impressions"], reverse=True)
    return out


def get_site_monthly_trend() -> list[dict]:
    start, end = _date_range()
    rows = _query(
        {
            "startDate": start,
            "endDate": end,
            "dimensions": ["date"],
            "rowLimit": 25000,
            "dataState": "final",
        }
    )
    by_month: dict[str, dict[str, float]] = defaultdict(
        lambda: {"clicks": 0.0, "impressions": 0.0, "pos_weight": 0.0}
    )
    for r in rows:
        month = r["keys"][0][:7]
        m = by_month[month]
        impr = float(r.get("impressions") or 0)
        m["clicks"] += float(r.get("clicks") or 0)
        m["impressions"] += impr
        m["pos_weight"] += float(r.get("position") or 0) * impr
    out = []
    for month in sorted(by_month.keys()):
        m = by_month[month]
        impr = m["impressions"]
        out.append(
            {
                "month": month,
                "clicks": int(m["clicks"]),
                "impressions": int(impr),
                "ctr": (m["clicks"] / impr) if impr else 0.0,
                "position": (m["pos_weight"] / impr) if impr else 0.0,
            }
        )
    return out


def get_top_queries_with_pages(limit: int = 40) -> list[dict]:
    """Top site queries with the best landing page for each."""
    start, end = _date_range()
    rows = _query_all(
        {
            "startDate": start,
            "endDate": end,
            "dimensions": ["query", "page"],
            "rowLimit": _API_MAX_ROWS,
            "dataState": "final",
        },
        label="top queries with pages",
    )
    best: dict[str, dict] = {}
    totals: dict[str, dict[str, float]] = defaultdict(
        lambda: {"clicks": 0.0, "impressions": 0.0}
    )
    for r in rows:
        q, page = r["keys"][0], r["keys"][1]
        m = _row_metrics(r)
        totals[q]["clicks"] += m["clicks"]
        totals[q]["impressions"] += m["impressions"]
        prev = best.get(q)
        if prev is None or m["impressions"] > prev["impressions"]:
            best[q] = {"page": page, **m}

    out = []
    for q, tot in totals.items():
        b = best[q]
        out.append(
            {
                "query": q,
                "clicks": tot["clicks"],
                "impressions": tot["impressions"],
                "ctr": (tot["clicks"] / tot["impressions"]) if tot["impressions"] else 0.0,
                "top_page": b["page"],
                "top_page_position": b["position"],
                "top_page_clicks": b["clicks"],
                "top_page_impressions": b["impressions"],
            }
        )
    out.sort(key=lambda x: x["impressions"], reverse=True)
    return out[:limit]


def collect_page_enrichment(page_url: str) -> dict[str, Any]:
    """All useful per-page GSC slices for the Claude briefing."""
    return {
        "queries": get_page_queries(page_url, limit=50),
        "period_comparison": get_page_period_comparison(page_url),
        "devices": get_page_devices(page_url),
        "countries": get_page_countries(page_url, limit=8),
        "monthly_trend": get_page_monthly_trend(page_url),
    }


def get_site_context() -> dict[str, Any]:
    """Site-level GSC context (once per run)."""
    cur_start, cur_end = _date_range()
    prev_start, prev_end = _prior_date_range()
    return {
        "date_range": {
            "current": {"start": cur_start, "end": cur_end, "days": config.DATE_RANGE_DAYS},
            "previous": {
                "start": prev_start,
                "end": prev_end,
                "days": config.DATE_RANGE_DAYS,
            },
        },
        "query_opportunities": get_site_query_opportunities(),
        "cannibalization": get_query_cannibalization(),
        "countries": get_site_countries(),
        "devices": get_site_devices(),
        "search_appearance": get_search_appearance(),
        "monthly_trend": get_site_monthly_trend(),
        "top_queries_with_pages": get_top_queries_with_pages(),
        "notes": [
            "All metrics from Google Search Console (final data, ~3 day lag).",
            "query_opportunities = demand with weak CTR/position.",
            "cannibalization = same query on multiple URLs.",
            "search_appearance = rich result types if Google shows any.",
            "Keyword volume/competition come from Google Ads Keyword Planner when configured.",
            "Bing is optional complementary engine data when BING_API_KEY is set.",
        ],
    }


def seed_keywords_from_context(
    site_context: dict[str, Any],
    page_results: list[dict],
    *,
    limit: int = 25,
) -> list[str]:
    """Build seed list for Keyword Planner from GSC queries."""
    seeds: list[str] = []
    seen: set[str] = set()

    def _add(q: str) -> None:
        q = (q or "").strip().lower()
        if len(q) < 2 or q in seen:
            return
        seen.add(q)
        seeds.append(q)

    for o in site_context.get("query_opportunities") or []:
        _add(o.get("query") or "")
    for t in site_context.get("top_queries_with_pages") or []:
        _add(t.get("query") or "")
    for r in page_results:
        for q in (r.get("queries") or [])[:8]:
            _add(q.get("query") or "")
    return seeds[:limit]
