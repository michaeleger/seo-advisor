"""
Google Ads Keyword Planner enrichment (volume / competition / CPC).

Requires a Google Ads account + OAuth + customer ID.
As of Sep 2026, API access level lives on the Cloud project (Basic/Explorer);
developer_token is optional/ignored by Google but still accepted if set.
Setup: see SETUP.md "Google Ads Keyword Planner".

Gracefully no-ops when credentials are missing so the semi-auto GSC path still works.
"""
from __future__ import annotations

import logging
from typing import Any

import config

log = logging.getLogger(__name__)

# English (US) language + United States geo — override via env if needed
_LANGUAGE_ID = "1000"  # English
_GEO_TARGET_US = "2840"  # United States


def is_configured() -> bool:
    # Developer token sunset Sep 2026 — Cloud project Basic access is the gate.
    # Token still sent if present for older client libs; not required to enable.
    return bool(
        config.GOOGLE_ADS_CUSTOMER_ID
        and config.GOOGLE_ADS_REFRESH_TOKEN
        and config.GOOGLE_ADS_CLIENT_ID
        and config.GOOGLE_ADS_CLIENT_SECRET
    )


def status_message() -> str:
    if is_configured():
        cid = config.GOOGLE_ADS_CUSTOMER_ID.replace("-", "")
        masked = ("*" * max(0, len(cid) - 4)) + cid[-4:] if cid else "?"
        return (
            f"configured (customer={masked}, "
            f"geo={config.GOOGLE_ADS_GEO_TARGET_IDS})"
        )
    missing = []
    if not config.GOOGLE_ADS_CUSTOMER_ID:
        missing.append("GOOGLE_ADS_CUSTOMER_ID")
    if not config.GOOGLE_ADS_REFRESH_TOKEN:
        missing.append("GOOGLE_ADS_REFRESH_TOKEN")
    if not config.GOOGLE_ADS_CLIENT_ID or not config.GOOGLE_ADS_CLIENT_SECRET:
        missing.append("GOOGLE_ADS_CLIENT_ID/SECRET")
    return "not configured — missing " + ", ".join(missing)


def _client():
    from google.ads.googleads.client import GoogleAdsClient

    cfg = {
        # Empty string OK after Sep 2026 sunset; Google ignores the header.
        "developer_token": config.GOOGLE_ADS_DEVELOPER_TOKEN or "",
        "client_id": config.GOOGLE_ADS_CLIENT_ID,
        "client_secret": config.GOOGLE_ADS_CLIENT_SECRET,
        "refresh_token": config.GOOGLE_ADS_REFRESH_TOKEN,
        "use_proto_plus": True,
    }
    if config.GOOGLE_ADS_LOGIN_CUSTOMER_ID:
        cfg["login_customer_id"] = config.GOOGLE_ADS_LOGIN_CUSTOMER_ID.replace("-", "")
    return GoogleAdsClient.load_from_dict(cfg)


def _customer_id() -> str:
    return config.GOOGLE_ADS_CUSTOMER_ID.replace("-", "")


def _geo_ids() -> list[str]:
    raw = config.GOOGLE_ADS_GEO_TARGET_IDS or _GEO_TARGET_US
    return [g.strip() for g in raw.split(",") if g.strip()]


def _set_seed(request, seeds: list[str], page_url: str | None) -> None:
    """
    Fill the request's `seed` oneof with exactly ONE member.

    keyword_seed, url_seed and keyword_and_url_seed are mutually exclusive:
    assigning url_seed after keyword_seed silently clears the keywords, so
    the old code sent a URL-only request whenever both were supplied.
    """
    seeds = seeds[:20]
    if seeds and page_url:
        request.keyword_and_url_seed.keywords.extend(seeds)
        request.keyword_and_url_seed.url = page_url
    elif seeds:
        request.keyword_seed.keywords.extend(seeds)
    elif page_url:
        request.url_seed.url = page_url


def _build_idea_request(
    client, customer_id: str, seeds: list[str], page_url: str | None
):
    request = client.get_type("GenerateKeywordIdeasRequest")
    request.customer_id = customer_id
    ads_service = client.get_service("GoogleAdsService")
    request.language = ads_service.language_constant_path(_LANGUAGE_ID)
    for geo in _geo_ids():
        request.geo_target_constants.append(ads_service.geo_target_constant_path(geo))
    request.include_adult_keywords = False
    request.keyword_plan_network = client.enums.KeywordPlanNetworkEnum.GOOGLE_SEARCH
    _set_seed(request, seeds, page_url)
    return request


def fetch_keyword_ideas(seed_keywords: list[str], *, page_url: str | None = None) -> list[dict]:
    """
    Generate keyword ideas + historical metrics from seed phrases and/or a page URL.
    Returns empty list if not configured or on API error (logged).
    """
    seeds = [s.strip() for s in seed_keywords if s and s.strip()]
    if not is_configured():
        log.info("Keyword Planner skipped: %s", status_message())
        return []
    if not seeds and not page_url:
        return []

    try:
        client = _client()
        idea_service = client.get_service("KeywordPlanIdeaService")
        request = _build_idea_request(client, _customer_id(), seeds, page_url)
        response = idea_service.generate_keyword_ideas(request=request)
        out: list[dict] = []
        for idea in response:
            metrics = idea.keyword_idea_metrics
            # enum competition: UNSPECIFIED, UNKNOWN, LOW, MEDIUM, HIGH
            competition = metrics.competition.name if metrics.competition else "UNKNOWN"
            out.append(
                {
                    "keyword": idea.text,
                    "avg_monthly_searches": int(metrics.avg_monthly_searches or 0),
                    "competition": competition,
                    "competition_index": int(metrics.competition_index or 0)
                    if metrics.competition_index
                    else None,
                    "low_top_of_page_bid_micros": int(metrics.low_top_of_page_bid_micros or 0)
                    or None,
                    "high_top_of_page_bid_micros": int(metrics.high_top_of_page_bid_micros or 0)
                    or None,
                    "low_top_of_page_bid_usd": (
                        round(metrics.low_top_of_page_bid_micros / 1_000_000, 2)
                        if metrics.low_top_of_page_bid_micros
                        else None
                    ),
                    "high_top_of_page_bid_usd": (
                        round(metrics.high_top_of_page_bid_micros / 1_000_000, 2)
                        if metrics.high_top_of_page_bid_micros
                        else None
                    ),
                }
            )
        out.sort(key=lambda x: x["avg_monthly_searches"], reverse=True)
        log.info("Keyword Planner returned %d ideas from %d seeds.", len(out), len(seeds))
        return out[:80]
    except ImportError:
        log.warning(
            "google-ads package not installed. Run: pip install google-ads"
        )
        return []
    except Exception as exc:
        log.warning("Keyword Planner API failed: %s", exc)
        return []


def fetch_historical_metrics(keywords: list[str]) -> list[dict]:
    """Look up historical metrics for exact seed keywords (volume/competition)."""
    kws = [k.strip() for k in keywords if k and k.strip()]
    if not is_configured() or not kws:
        return []
    try:
        client = _client()
        customer_id = _customer_id()
        idea_service = client.get_service("KeywordPlanIdeaService")
        request = client.get_type("GenerateKeywordHistoricalMetricsRequest")
        request.customer_id = customer_id
        request.keywords.extend(kws[:50])
        request.language = client.get_service("GoogleAdsService").language_constant_path(
            _LANGUAGE_ID
        )
        for geo in _geo_ids():
            request.geo_target_constants.append(
                client.get_service("GoogleAdsService").geo_target_constant_path(geo)
            )
        request.keyword_plan_network = (
            client.enums.KeywordPlanNetworkEnum.GOOGLE_SEARCH
        )
        response = idea_service.generate_keyword_historical_metrics(request=request)
        out = []
        for result in response.results:
            metrics = result.keyword_metrics
            out.append(
                {
                    "keyword": result.text,
                    "avg_monthly_searches": int(metrics.avg_monthly_searches or 0),
                    "competition": metrics.competition.name if metrics.competition else "UNKNOWN",
                    "competition_index": int(metrics.competition_index or 0)
                    if metrics.competition_index
                    else None,
                    "low_top_of_page_bid_usd": (
                        round(metrics.low_top_of_page_bid_micros / 1_000_000, 2)
                        if metrics.low_top_of_page_bid_micros
                        else None
                    ),
                    "high_top_of_page_bid_usd": (
                        round(metrics.high_top_of_page_bid_micros / 1_000_000, 2)
                        if metrics.high_top_of_page_bid_micros
                        else None
                    ),
                }
            )
        return out
    except Exception as exc:
        log.warning("Keyword historical metrics failed: %s", exc)
        return []


def enrich_for_briefing(
    seed_keywords: list[str],
    *,
    sample_page_url: str | None = None,
) -> dict[str, Any]:
    """
    Bundle for the Claude handoff. Safe when Ads is not set up yet.
    """
    status = status_message()
    if not is_configured():
        return {
            "enabled": False,
            "status": status,
            "seed_keywords": seed_keywords[:25],
            "ideas": [],
            "historical_for_seeds": [],
            "setup_hint": (
                "Open a Google Ads account, get a developer token (Basic access), "
                "run python authorize_ads.py, set GOOGLE_ADS_* in .env — then re-run."
            ),
        }

    ideas = fetch_keyword_ideas(seed_keywords, page_url=sample_page_url)
    historical = fetch_historical_metrics(seed_keywords[:30])
    return {
        "enabled": True,
        "status": status,
        "seed_keywords": seed_keywords[:25],
        "geo_target_ids": _geo_ids(),
        "language_id": _LANGUAGE_ID,
        "ideas": ideas,
        "historical_for_seeds": historical,
    }
