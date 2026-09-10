"""
Shared fixtures.

The important one is `pinned_config`. `config.py` calls
`load_dotenv(override=True)` at import, and `analyzer` reads its thresholds
from `config` as module globals at call time. Without pinning, a test asserting
"thin rows are filtered below MIN_IMPRESSIONS=10" would pass on a clean
checkout and fail on a machine whose .env sets MIN_IMPRESSIONS=1 — a suite
whose result depends on who runs it is worse than no suite.

Every test therefore runs against explicit values, and overrides the single
knob it is exercising.
"""
from __future__ import annotations

import pytest

import config

# What analyzer reads. Values chosen to be readable in assertions, not to
# mirror any particular .env.
_DEFAULTS = {
    "GSC_SITE_URL": "https://example.com/",
    "DATE_RANGE_DAYS": 90,
    "MIN_IMPRESSIONS": 10,
    "MAX_CTR": 0.05,
    "MAX_POSITION": 20.0,
    "MAX_POSTS_TO_ANALYZE": 10,
    "PRIORITIZE_BY_RANKMATH": True,
    "RANKMATH_SKIP_SCORE": 80,
    "SKIP_PATH_SEGMENTS": (
        "/category/",
        "/tag/",
        "/author/",
        "/page/",
        "/wp-json/",
        "/wp-admin/",
        "/feed/",
    ),
    "SKIP_SLUGS": frozenset(
        {"", "home", "about", "contact", "privacy-policy", "cookie-policy",
         "terms", "terms-of-service"}
    ),
    "SKIP_SLUG_SUBSTRINGS": ("privacy-policy", "cookie", "terms-of"),
    # Neglect / demand scoring
    "NEGLECT_FULL_DAYS": 730,
    "NEGLECT_MAX_MULTIPLIER": 3.0,
    "TARGET_POSITION": 5.0,
    "DECAY_WINDOW_DAYS": 90,
    "INCLUDE_ZERO_TRAFFIC_PAGES": False,
    # Backoff
    "BACKOFF_DAYS": (30, 60, 90, 180),
    "EDIT_COOLDOWN_DAYS": 90,
}


@pytest.fixture(autouse=True)
def pinned_config(monkeypatch):
    """Pin every config value the analyzer reads. Autouse — no opting out."""
    for name, value in _DEFAULTS.items():
        monkeypatch.setattr(config, name, value, raising=False)
    return config


@pytest.fixture
def gsc_row():
    """Build a Search Console page row."""
    def _make(page, *, clicks=5, impressions=500, ctr=0.01, position=15.0):
        return {
            "page": page,
            "clicks": clicks,
            "impressions": impressions,
            "ctr": ctr,
            "position": position,
        }
    return _make


@pytest.fixture
def wp_post():
    """Build a WordPress post carrying a Rank Math score."""
    def _make(url, *, score=None, focus="", title="A Post", post_id=1):
        return {
            "id": post_id,
            "title": title,
            "url": url,
            "content_plain": "",
            "rankmath": {"seo_score": score, "focus_keyword": focus},
        }
    return _make
