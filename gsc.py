"""Google Search Console API client."""
from datetime import date, timedelta
import os

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

import config

_SCOPES = ["https://www.googleapis.com/auth/webmasters.readonly"]
_TOKEN_FILE = "token.json"
_service = None


def _get_credentials() -> Credentials:
    creds = None
    if os.path.exists(_TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(_TOKEN_FILE, _SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                config.GSC_CREDENTIALS_FILE, _SCOPES
            )
            creds = flow.run_local_server(port=0)
        with open(_TOKEN_FILE, "w") as f:
            f.write(creds.to_json())
    return creds


def _get_service():
    global _service
    if _service is None:
        _service = build("searchconsole", "v1", credentials=_get_credentials(), cache_discovery=False)
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
