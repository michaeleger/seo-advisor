"""
PageSpeed stage: key gate, 429 circuit breaker, and error redaction.

The 2026-09-10 run had no PAGESPEED_API_KEY, so PSI answered HTTP 429 to every
request. The stage kept going anyway — one wasted request per selected URL —
and pasted the 429 body, which names the calling Google project number,
straight into the Markdown briefing that gets handed to a chat model.

These tests pin the three halves of that: never start without a key, stop at
the first 429, and never let a response body reach the report.
"""
from __future__ import annotations

import pytest
import requests

import briefing
import pagespeed

# A real PSI 429 body: it names the project, and it is exactly what must not
# survive into the report.
QUOTA_BODY = (
    '{"error": {"code": 429, "message": "Quota exceeded for quota metric '
    "'Queries' and limit 'Queries per minute' of service "
    "'pagespeedonline.googleapis.com' for consumer "
    '\'project_number:481516234211\'.", "status": "RESOURCE_EXHAUSTED"}}'
)
PROJECT_NUMBER = "481516234211"


class FakeResponse:
    def __init__(self, payload=None, *, status=200, text=""):
        self._payload = payload if payload is not None else {}
        self.status_code = status
        self.text = text

    def json(self):
        return self._payload


class RecordingGet:
    """Stands in for requests.get and remembers every URL it was asked for."""

    def __init__(self, responder):
        self._responder = responder
        self.calls: list[str] = []

    def __call__(self, api, params=None, timeout=None):
        url = dict(params or {}).get("url", "")
        self.calls.append(url)
        result = self._responder(url, dict(params or {}))
        if isinstance(result, Exception):
            raise result
        return result


def lighthouse_ok():
    return FakeResponse(
        {
            "lighthouseResult": {
                "finalUrl": "https://example.com/a/",
                "categories": {"performance": {"score": 0.42}},
                "audits": {},
            }
        }
    )


@pytest.fixture
def psi_config(monkeypatch):
    """Keyed, single-strategy, no sleeping."""
    config_mod = pagespeed.config
    monkeypatch.setattr(config_mod, "USE_PAGESPEED", True, raising=False)
    monkeypatch.setattr(config_mod, "PAGESPEED_API_KEY", "test-key", raising=False)
    monkeypatch.setattr(config_mod, "PAGESPEED_STRATEGIES", ["mobile"], raising=False)
    monkeypatch.setattr(config_mod, "PAGESPEED_PAUSE_SECONDS", 0.0, raising=False)
    monkeypatch.setattr(config_mod, "PAGESPEED_TIMEOUT_SECONDS", 5, raising=False)
    return config_mod


URLS = [
    "https://example.com/a/",
    "https://example.com/b/",
    "https://example.com/c/",
]


class TestKeyGate:
    def test_missing_key_is_not_configured_even_when_enabled(self, psi_config, monkeypatch):
        monkeypatch.setattr(psi_config, "PAGESPEED_API_KEY", "", raising=False)
        assert psi_config.USE_PAGESPEED is True
        assert pagespeed.is_configured() is False

    def test_missing_key_scans_nothing(self, psi_config, monkeypatch):
        monkeypatch.setattr(psi_config, "PAGESPEED_API_KEY", "", raising=False)

        def explode(*a, **kw):
            raise AssertionError("PSI was called without an API key")

        monkeypatch.setattr(requests, "get", explode)

        out = pagespeed.scan_selected_urls(URLS)

        assert out["enabled"] is False
        assert out["scanned"] == 0
        assert out["pages"] == {}

    def test_skip_status_says_why(self, psi_config, monkeypatch):
        monkeypatch.setattr(psi_config, "PAGESPEED_API_KEY", "   ", raising=False)
        status = pagespeed.scan_selected_urls(URLS)["status"]
        assert "PAGESPEED_API_KEY" in status
        assert "skipped" in status.lower()

    def test_disabled_still_skips(self, psi_config, monkeypatch):
        monkeypatch.setattr(psi_config, "USE_PAGESPEED", False, raising=False)
        assert pagespeed.is_configured() is False
        assert "USE_PAGESPEED=0" in pagespeed.scan_selected_urls(URLS)["status"]

    def test_key_present_runs_the_stage(self, psi_config, monkeypatch):
        get = RecordingGet(lambda url, params: lighthouse_ok())
        monkeypatch.setattr(requests, "get", get)

        out = pagespeed.scan_selected_urls(URLS)

        assert get.calls == URLS
        assert out["enabled"] is True
        assert out["ok_count"] == 3


class TestRateLimitBreaker:
    def test_first_429_stops_the_scan(self, psi_config, monkeypatch):
        get = RecordingGet(
            lambda url, params: FakeResponse(status=429, text=QUOTA_BODY)
        )
        monkeypatch.setattr(requests, "get", get)

        out = pagespeed.scan_selected_urls(URLS)

        assert get.calls == [URLS[0]], "kept hammering PSI after a 429"
        assert out["stopped_early"] is True
        assert out["scanned"] == 1

    def test_429_mid_run_keeps_what_already_succeeded(self, psi_config, monkeypatch):
        def responder(url, params):
            if url == URLS[0]:
                return lighthouse_ok()
            return FakeResponse(status=429, text=QUOTA_BODY)

        get = RecordingGet(responder)
        monkeypatch.setattr(requests, "get", get)

        out = pagespeed.scan_selected_urls(URLS)

        assert get.calls == URLS[:2]
        assert out["ok_count"] == 1
        assert out["pages"][URLS[0]]["ok"] is True

    def test_429_does_not_try_the_second_strategy(self, psi_config, monkeypatch):
        monkeypatch.setattr(
            psi_config, "PAGESPEED_STRATEGIES", ["mobile", "desktop"], raising=False
        )
        get = RecordingGet(
            lambda url, params: FakeResponse(status=429, text=QUOTA_BODY)
        )
        monkeypatch.setattr(requests, "get", get)

        pagespeed.scan_selected_urls(URLS[:1])

        assert len(get.calls) == 1

    def test_a_429_inside_the_json_body_also_breaks(self, psi_config, monkeypatch):
        """PSI sometimes answers 200 with an error envelope."""
        get = RecordingGet(
            lambda url, params: FakeResponse(
                {"error": {"code": 429, "message": f"project_number:{PROJECT_NUMBER}"}}
            )
        )
        monkeypatch.setattr(requests, "get", get)

        out = pagespeed.scan_selected_urls(URLS)

        assert get.calls == [URLS[0]]
        assert out["stopped_early"] is True

    def test_a_non_429_failure_does_not_stop_the_run(self, psi_config, monkeypatch):
        """Only quota exhaustion is global; one bad page is just one bad page."""
        def responder(url, params):
            if url == URLS[0]:
                return FakeResponse(status=500, text="upstream boom")
            return lighthouse_ok()

        get = RecordingGet(responder)
        monkeypatch.setattr(requests, "get", get)

        out = pagespeed.scan_selected_urls(URLS)

        assert get.calls == URLS
        assert out["stopped_early"] is False
        assert out["ok_count"] == 2


class TestErrorsCarryNoBody:
    def test_429_error_string_has_no_body_or_project_number(self, psi_config, monkeypatch):
        monkeypatch.setattr(
            requests,
            "get",
            RecordingGet(lambda url, params: FakeResponse(status=429, text=QUOTA_BODY)),
        )

        err = pagespeed.analyze_url(URLS[0])["error"]

        assert "429" in err
        assert PROJECT_NUMBER not in err
        assert "project_number" not in err
        assert "{" not in err and "Quota exceeded" not in err

    def test_json_error_envelope_is_not_echoed(self, psi_config, monkeypatch):
        monkeypatch.setattr(
            requests,
            "get",
            RecordingGet(
                lambda url, params: FakeResponse(
                    {
                        "error": {
                            "code": 403,
                            "message": f"consumer 'project_number:{PROJECT_NUMBER}' blocked",
                        }
                    }
                )
            ),
        )

        err = pagespeed.analyze_url(URLS[0])["error"]

        assert PROJECT_NUMBER not in err
        assert "project_number" not in err

    def test_transport_errors_do_not_leak_the_request_url(self, psi_config, monkeypatch):
        """`requests` puts the full URL — `?key=` and all — in its messages."""
        boom = requests.ConnectionError(
            "HTTPSConnectionPool(host='www.googleapis.com', port=443): "
            "Max retries exceeded with url: /pagespeedonline/v5/runPagespeed"
            "?url=https://example.com/a/&key=test-key"
        )
        monkeypatch.setattr(requests, "get", RecordingGet(lambda url, params: boom))

        err = pagespeed.analyze_url(URLS[0])["error"]

        assert "test-key" not in err
        assert "googleapis.com" not in err
        assert "ConnectionError" in err

    def test_status_line_survives_as_plain_text(self, psi_config, monkeypatch):
        monkeypatch.setattr(
            requests,
            "get",
            RecordingGet(lambda url, params: FakeResponse(status=429, text=QUOTA_BODY)),
        )
        status = pagespeed.scan_selected_urls(URLS)["status"]
        assert PROJECT_NUMBER not in status
        assert "429" in status


class TestBriefingRedaction:
    """The render-side guarantee, independent of what pagespeed.py produces."""

    def test_sanitizer_drops_a_json_body(self):
        safe = briefing._safe_stage_error(f"PSI HTTP 429: {QUOTA_BODY}")
        assert PROJECT_NUMBER not in safe
        assert "{" not in safe

    def test_sanitizer_redacts_long_digit_runs(self):
        assert PROJECT_NUMBER not in briefing._safe_stage_error(
            f"consumer project_number:{PROJECT_NUMBER}"
        )

    def test_sanitizer_keeps_short_numbers(self):
        assert "429" in briefing._safe_stage_error("HTTP 429 — rate limited")

    def test_sanitizer_is_one_line_and_bounded(self):
        safe = briefing._safe_stage_error("boom\nsecond line " + "x" * 500)
        assert "\n" not in safe
        assert len(safe) <= briefing._PSI_ERROR_MAX_CHARS + 1

    def test_sanitizer_handles_empty_and_none(self):
        assert briefing._safe_stage_error(None) == "unknown error"
        assert briefing._safe_stage_error("") == "unknown error"
        assert briefing._safe_stage_error(QUOTA_BODY) == "unknown error"

    def test_a_poisoned_error_cannot_reach_the_markdown(self):
        """Even if some future caller stuffs a raw body into ps['error']."""
        post = {
            "id": 1,
            "title": "A Post",
            "url": "https://example.com/a/",
            "content_plain": "",
            "rankmath": {"seo_score": 40, "focus_keyword": ""},
        }
        result = {
            "metrics": {"page": post["url"], "clicks": 1, "impressions": 100,
                        "ctr": 0.01, "position": 20.0, "reasons": []},
            "post": post,
            "pagespeed": {"url": post["url"], "ok": False, "error": QUOTA_BODY},
        }
        md = briefing.briefing_to_markdown(
            briefing.build_briefing_payload(
                [result],
                site="https://example.com/",
                pagespeed={"enabled": False, "status": f"error: {QUOTA_BODY}", "pages": {}},
            )
        )

        assert PROJECT_NUMBER not in md
        assert "RESOURCE_EXHAUSTED" not in md
        assert "Quota exceeded" not in md
