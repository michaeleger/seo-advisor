"""Google Search Console API client."""
from datetime import date, timedelta

from google.oauth2 import service_account
from googleapiclient.discovery import build

import config

_SCOPES = ["https://www.googleapis.com/auth/webmasters.readonly"]
_service = None


def _get_service():
    global _service
    if _service is None:
        creds = service_account.Credentials.from_service_account_file(
            config.GSC_CREDENTIALS_FILE, scopes=_SCOPES
        )
        _service = build("searchconsole", "v1", credentials=creds, cache_discovery=False)
    return _service


def _date_range() -> tuple[str, str]:
    end = date.today() - timedelta(days=3)   # GSC data lags ~3 days
    start = end - timedelta(days=config.DATE_RANGE_DAYS)
    return start.isoformat(), end.isoformat()


def get_page_metrics() -> list[dict]:
    """Return one row per page with aggregated clicks/impressions/ctr/position."""
    start, end = _date_range()
    resp = (
        _get_service()
        .searchanalytics()
        .query(
            siteUrl=config.GSC_SITE_URL,
            body={
                "startDate": start,
                "endDate": end,
                "dimensions": ["page"],
                "rowLimit": 1000,
                "dataState": "final",
            },
        )
        .execute()
    )
    rows = resp.get("rows", [])
    return [
        {
            "page": r["keys"][0],
            "clicks": r["clicks"],
            "impressions": r["impressions"],
            "ctr": r["ctr"],
            "position": r["position"],
        }
        for r in rows
    ]


def get_page_queries(page_url: str, limit: int = 20) -> list[dict]:
    """Return the top search queries driving impressions to a specific page."""
    start, end = _date_range()
    resp = (
        _get_service()
        .searchanalytics()
        .query(
            siteUrl=config.GSC_SITE_URL,
            body={
                "startDate": start,
                "endDate": end,
                "dimensions": ["query"],
                "dimensionFilterGroups": [
                    {
                        "filters": [
                            {
                                "dimension": "page",
                                "operator": "equals",
                                "expression": page_url,
                            }
                        ]
                    }
                ],
                "rowLimit": limit,
                "orderBy": [{"fieldName": "impressions", "sortOrder": "DESCENDING"}],
                "dataState": "final",
            },
        )
        .execute()
    )
    rows = resp.get("rows", [])
    return [
        {
            "query": r["keys"][0],
            "clicks": r["clicks"],
            "impressions": r["impressions"],
            "ctr": r["ctr"],
            "position": r["position"],
        }
        for r in rows
    ]
