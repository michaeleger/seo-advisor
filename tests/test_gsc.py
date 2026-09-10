"""
Search Console pagination.

Search Console caps a response at 25 000 rows and pages via startRow. A single
capped request truncates silently on any site with real traffic — you get a
partial picture with no error. These tests drive _query_all against a stub so
no network or credentials are involved.
"""
from __future__ import annotations

import gsc


def make_rows(n, offset=0, n_keys=1):
    return [
        {
            # one key per requested dimension, as the real API returns
            "keys": [f"k{d}-{offset + i}" for d in range(n_keys)],
            "clicks": 1, "impressions": 10, "ctr": 0.1, "position": 5.0,
        }
        for i in range(n)
    ]


class FakeAPI:
    """Records the bodies it was called with and serves a fixed row set."""

    def __init__(self, total):
        self.total = total
        self.bodies = []

    def __call__(self, body):
        self.bodies.append(body)
        start = body.get("startRow", 0)
        size = body["rowLimit"]
        n_keys = max(1, len(body.get("dimensions") or ["x"]))
        return make_rows(
            max(0, min(size, self.total - start)), offset=start, n_keys=n_keys
        )

    @property
    def start_rows(self):
        return [b.get("startRow") for b in self.bodies]


class TestQueryAll:
    def test_single_short_page_makes_one_request(self, monkeypatch):
        api = FakeAPI(total=42)
        monkeypatch.setattr(gsc, "_query", api)
        rows = gsc._query_all({"rowLimit": 25000})
        assert len(rows) == 42
        assert len(api.bodies) == 1

    def test_pages_until_exhausted(self, monkeypatch):
        api = FakeAPI(total=25_000 * 2 + 7)
        monkeypatch.setattr(gsc, "_query", api)
        rows = gsc._query_all({"rowLimit": 25000})
        assert len(rows) == 25_000 * 2 + 7
        assert api.start_rows == [0, 25_000, 50_000]

    def test_exact_multiple_needs_a_final_empty_request(self, monkeypatch):
        """A full last page is indistinguishable from more rows pending."""
        api = FakeAPI(total=50_000)
        monkeypatch.setattr(gsc, "_query", api)
        rows = gsc._query_all({"rowLimit": 25000})
        assert len(rows) == 50_000
        assert api.start_rows == [0, 25_000, 50_000]

    def test_no_rows_at_all(self, monkeypatch):
        api = FakeAPI(total=0)
        monkeypatch.setattr(gsc, "_query", api)
        assert gsc._query_all({"rowLimit": 25000}) == []
        assert len(api.bodies) == 1

    def test_max_rows_caps_the_result(self, monkeypatch):
        api = FakeAPI(total=10_000)
        monkeypatch.setattr(gsc, "_query", api)
        rows = gsc._query_all({"rowLimit": 25000}, max_rows=100)
        assert len(rows) == 100

    def test_request_size_never_exceeds_the_api_maximum(self, monkeypatch):
        api = FakeAPI(total=100)
        monkeypatch.setattr(gsc, "_query", api)
        gsc._query_all({"rowLimit": 999_999})
        assert all(b["rowLimit"] <= gsc._API_MAX_ROWS for b in api.bodies)

    def test_safety_cap_stops_runaway_paging_and_warns(self, monkeypatch, caplog):
        api = FakeAPI(total=10**9)
        monkeypatch.setattr(gsc, "_query", api)
        with caplog.at_level("WARNING"):
            rows = gsc._query_all({"rowLimit": 25000}, label="huge")
        assert len(api.bodies) == gsc._MAX_PAGES
        assert len(rows) == gsc._MAX_PAGES * 25_000
        assert "truncated" in caplog.text

    def test_body_fields_are_preserved_across_pages(self, monkeypatch):
        api = FakeAPI(total=30_000)
        monkeypatch.setattr(gsc, "_query", api)
        gsc._query_all(
            {
                "rowLimit": 25000,
                "startDate": "2026-01-01",
                "endDate": "2026-03-01",
                "dimensions": ["query", "page"],
                "dataState": "final",
            }
        )
        assert len(api.bodies) == 2
        for body in api.bodies:
            assert body["dimensions"] == ["query", "page"]
            assert body["startDate"] == "2026-01-01"
            assert body["dataState"] == "final"


class TestAggregateQueriesPaginate:
    """The four whole-site extracts must page; per-page slices need not."""

    def _stub(self, monkeypatch, total):
        api = FakeAPI(total=total)
        monkeypatch.setattr(gsc, "_query", api)
        monkeypatch.setattr(gsc, "_date_range", lambda: ("2026-01-01", "2026-03-01"))
        return api

    def test_get_page_metrics_pages(self, monkeypatch):
        api = self._stub(monkeypatch, 30_000)
        assert len(gsc.get_page_metrics()) == 30_000
        assert len(api.bodies) == 2

    def test_cannibalization_pages(self, monkeypatch):
        api = self._stub(monkeypatch, 30_000)
        gsc.get_query_cannibalization()
        assert len(api.bodies) == 2

    def test_top_queries_with_pages_pages(self, monkeypatch):
        api = self._stub(monkeypatch, 30_000)
        gsc.get_top_queries_with_pages()
        assert len(api.bodies) == 2

    def test_site_query_opportunities_pages(self, monkeypatch):
        api = self._stub(monkeypatch, 30_000)
        gsc.get_site_query_opportunities()
        assert len(api.bodies) == 2

    def test_per_page_slices_do_not_page(self, monkeypatch):
        api = self._stub(monkeypatch, 30_000)
        gsc.get_page_queries("https://example.com/p/", limit=50)
        assert len(api.bodies) == 1
