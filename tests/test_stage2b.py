"""
B3: Search Console retries, and Stage 2b surviving one bad page.

`_query` called `.execute()` with no retries, so a single transient 5xx on any
of a page's per-page calls failed that page. Stage 2b then re-raised any
RuntimeError, ending the run — no report for the pages that were fine.
"""
from __future__ import annotations

import httplib2
import pytest
from googleapiclient.errors import HttpError

import gsc
import main
import seo_advisor
import wp_client

URLS = [f"https://example.com/p{i}/" for i in range(1, 5)]


def selected(url):
    return {"page": url, "clicks": 1, "impressions": 500, "ctr": 0.002,
            "position": 15.0, "times_suggested": 0}


def http_error(status):
    return HttpError(httplib2.Response({"status": status}), b"{}", uri="x")


@pytest.fixture
def stage(monkeypatch):
    """Stub every external call Stage 2b makes; `fail_on` injects errors."""
    fail_on: dict[str, BaseException] = {}
    enriched: list[str] = []

    def fake_post(url):
        return {"id": 1, "title": url, "url": url, "modified": "",
                "content_plain": "", "rankmath": {}, "type": "post"}

    def fake_enrich(url):
        if url in fail_on:
            raise fail_on[url]
        enriched.append(url)
        return {"queries": [], "period_comparison": {}, "devices": [],
                "countries": [], "monthly_trend": []}

    monkeypatch.setattr(wp_client, "get_post_content", fake_post)
    monkeypatch.setattr(gsc, "collect_page_enrichment", fake_enrich)
    monkeypatch.setattr(main.db, "get_page_state", lambda url: None)
    return fail_on, enriched


def run(pages):
    return main.enrich_selected_pages([selected(u) for u in pages])


class TestStage2bContinues:
    @pytest.mark.parametrize("exc", [
        RuntimeError("boom"),
        http_error(500),
        TimeoutError("read timed out"),
        seo_advisor.requests.ConnectionError("reset"),
    ])
    def test_mid_loop_failure_still_processes_later_urls(self, stage, exc):
        fail_on, enriched = stage
        fail_on[URLS[1]] = exc

        results, pending = run(URLS)

        processed = [r["metrics"]["page"] for r in results]
        assert processed == [URLS[0], URLS[2], URLS[3]]
        assert enriched == [URLS[0], URLS[2], URLS[3]]
        assert [p[0] for p in pending] == processed

    @pytest.mark.parametrize("exc", [
        gsc.GSCAuthError("token revoked"),
        http_error(401),
        http_error(403),
        seo_advisor.LocalLLMConfigError("bad provider"),
    ])
    def test_auth_fatal_errors_still_abort(self, stage, exc):
        fail_on, enriched = stage
        fail_on[URLS[1]] = exc

        with pytest.raises(type(exc)):
            run(URLS)
        assert enriched == [URLS[0]]


class TestAuthFatal:
    def test_classification(self):
        assert gsc.is_auth_fatal(gsc.GSCAuthError("x"))
        assert gsc.is_auth_fatal(http_error(401))
        assert gsc.is_auth_fatal(
            FileNotFoundError("token.json not found. Run `python authorize.py`")
        )
        assert not gsc.is_auth_fatal(http_error(500))
        assert not gsc.is_auth_fatal(http_error(429))
        assert not gsc.is_auth_fatal(RuntimeError("x"))

    def test_credential_errors_are_auth_errors(self):
        """Still RuntimeErrors, so older `except RuntimeError` callers keep working."""
        assert issubclass(gsc.GSCAuthError, RuntimeError)


class TestRetries:
    def test_query_asks_the_client_library_to_retry(self, monkeypatch):
        seen = {}

        class Request:
            def execute(self, **kwargs):
                seen.update(kwargs)
                return {"rows": [{"keys": ["a"]}]}

        class Service:
            def searchanalytics(self):
                return self

            def query(self, siteUrl, body):
                return Request()

        monkeypatch.setattr(gsc, "_get_service", lambda: Service())

        assert gsc._query({"rowLimit": 1}) == [{"keys": ["a"]}]
        assert seen.get("num_retries", 0) >= 3
