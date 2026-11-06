"""
WordPress catalog paging.

The 2026-09-10 run fetched `posts` and `pages` out of one 300-item budget,
newest-modified first. The site has more than 300 posts, so `pages` was never
requested at all: every page reached the ranker with no `modified` and no Rank
Math score, which pins neglect_multiplier at 1.0. The pages most likely to be
neglected were the ones structurally unable to be ranked as neglected.
"""
from __future__ import annotations

import logging

import pytest

import analyzer
import wp_client


class FakeResponse:
    def __init__(self, payload, *, status=200, total_pages=1):
        self._payload = payload
        self.status_code = status
        self.headers = {"X-WP-TotalPages": str(total_pages)}
        self.content = b"[]"
        self.text = ""

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise AssertionError(f"HTTP {self.status_code}")


def wp_item(pid, *, kind="post", modified="2020-01-01T00:00:00"):
    return {
        "id": pid,
        "title": {"rendered": f"Item {pid}"},
        "content": {"rendered": "<p>body</p>"},
        "link": f"https://example.com/{kind}-{pid}/",
        "meta": {},
        "type": kind,
        "slug": f"{kind}-{pid}",
        "modified": modified,
    }


class FakeWP:
    """Minimal wp/v2 lister: honours page/per_page and reports total pages."""

    def __init__(self, **by_endpoint):
        self.items = by_endpoint
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, url, params=None, timeout=25):
        params = params or {}
        endpoint = url.rstrip("/").split("/")[-1]
        self.calls.append((endpoint, params))
        items = self.items.get(endpoint, [])
        per_page = int(params.get("per_page") or 10)
        page = int(params.get("page") or 1)
        total_pages = max(1, -(-len(items) // per_page))
        if page > total_pages:
            return FakeResponse([], status=400, total_pages=total_pages)
        start = (page - 1) * per_page
        return FakeResponse(
            items[start : start + per_page], total_pages=total_pages
        )


@pytest.fixture
def no_scores(monkeypatch):
    """Catalog paging under test, not the Rank Math overlay."""
    monkeypatch.setattr(wp_client, "fetch_rankmath_scores", lambda **kw: {})


@pytest.fixture
def fake_wp(monkeypatch, no_scores):
    def _install(**by_endpoint):
        fake = FakeWP(**by_endpoint)
        monkeypatch.setattr(wp_client, "_session_get", fake)
        return fake
    return _install


class TestSeparateBudgets:
    def test_pages_are_fetched_even_when_posts_would_fill_the_old_cap(
        self, fake_wp
    ):
        """350 posts > the old 300-item shared budget. Pages must still land."""
        fake = fake_wp(
            posts=[wp_item(i) for i in range(1, 351)],
            pages=[wp_item(900 + i, kind="page") for i in range(5)],
        )

        out = wp_client.list_content_with_rankmath(per_type_max=2000)

        kinds = [p["type"] for p in out]
        assert kinds.count("post") == 350
        assert kinds.count("page") == 5
        assert "pages" in {endpoint for endpoint, _ in fake.calls}

    def test_budget_is_per_type_so_a_full_post_budget_does_not_starve_pages(
        self, fake_wp
    ):
        """Even when posts hit their own cap, pages get their own full budget."""
        fake_wp(
            posts=[wp_item(i) for i in range(1, 501)],
            pages=[wp_item(900 + i, kind="page") for i in range(5)],
        )

        out = wp_client.list_content_with_rankmath(per_type_max=300)

        kinds = [p["type"] for p in out]
        assert kinds.count("post") == 300
        assert kinds.count("page") == 5

    def test_truncation_is_logged_not_silent(self, fake_wp, caplog):
        fake_wp(posts=[wp_item(i) for i in range(1, 501)], pages=[])

        with caplog.at_level(logging.WARNING, logger=wp_client.log.name):
            wp_client.list_content_with_rankmath(per_type_max=300)

        assert any("TRUNCATED" in r.message for r in caplog.records)

    def test_exhausting_a_type_under_budget_reports_no_truncation(
        self, fake_wp, caplog
    ):
        fake_wp(posts=[wp_item(i) for i in range(1, 301)], pages=[])

        with caplog.at_level(logging.WARNING, logger=wp_client.log.name):
            out = wp_client.list_content_with_rankmath(per_type_max=300)

        assert len(out) == 300
        assert not any("TRUNCATED" in r.message for r in caplog.records)

    def test_every_listed_item_is_returned_exactly_once(self, fake_wp):
        """A shrinking page size skipped items; paging must not lose any."""
        fake_wp(posts=[wp_item(i) for i in range(1, 251)], pages=[])

        out = wp_client.list_content_with_rankmath(per_type_max=250)

        assert sorted(p["id"] for p in out) == list(range(1, 251))


class TestOrdering:
    def test_catalog_is_requested_oldest_modified_first(self, fake_wp):
        """Newest-first truncation drops exactly the neglected content."""
        fake = fake_wp(posts=[wp_item(1)], pages=[wp_item(2, kind="page")])

        wp_client.list_content_with_rankmath(per_type_max=50)

        for endpoint, params in fake.calls:
            assert params["orderby"] == "modified"
            assert params["order"] == "asc", endpoint

    def test_truncation_drops_the_freshest_items(self, fake_wp):
        """Oldest-first: what survives a cap is the neglected end of the list."""
        fake_wp(
            posts=[
                wp_item(i, modified=f"20{10 + i:02d}-01-01T00:00:00")
                for i in range(1, 201)
            ],
            pages=[],
        )

        out = wp_client.list_content_with_rankmath(per_type_max=150)

        assert [p["id"] for p in out] == list(range(1, 151))


class TestRankMathStubs:
    """Scored posts the WP listing never returned still reach the ranker."""

    def test_stub_carries_modified_when_the_score_endpoint_supplies_it(
        self, monkeypatch, fake_wp
    ):
        fake_wp(posts=[], pages=[])
        monkeypatch.setattr(
            wp_client,
            "fetch_rankmath_scores",
            lambda **kw: {
                7: {
                    "id": 7,
                    "seo_score": 12,
                    "title": "Orphan",
                    "url": "https://example.com/orphan/",
                    "modified": "2019-03-04T05:06:07",
                    "focus_keyword": "orphan",
                }
            },
        )

        out = wp_client.list_content_with_rankmath(per_type_max=50)

        assert len(out) == 1
        assert out[0]["modified"] == "2019-03-04T05:06:07"

    def test_stub_with_modified_is_scored_as_neglected(self, monkeypatch, fake_wp):
        """The point of carrying `modified`: neglect stops collapsing to 1.0."""
        fake_wp(posts=[], pages=[])
        monkeypatch.setattr(
            wp_client,
            "fetch_rankmath_scores",
            lambda **kw: {
                7: {
                    "id": 7,
                    "seo_score": 12,
                    "title": "Orphan",
                    "url": "https://example.com/orphan/",
                    "modified": "2019-03-04T05:06:07",
                }
            },
        )

        stub = wp_client.list_content_with_rankmath(per_type_max=50)[0]
        days = analyzer._days_since(stub["modified"])

        assert days is not None and days > 730
        assert analyzer.neglect_multiplier(days) > 1.0

    def test_stub_without_modified_stays_neutral_rather_than_fresh(
        self, monkeypatch, fake_wp
    ):
        """Unknown edit date is unknown — not evidence the page was just touched."""
        fake_wp(posts=[], pages=[])
        monkeypatch.setattr(
            wp_client,
            "fetch_rankmath_scores",
            lambda **kw: {
                8: {"id": 8, "seo_score": 12, "url": "https://example.com/x/"}
            },
        )

        stub = wp_client.list_content_with_rankmath(per_type_max=50)[0]

        assert stub["modified"] == ""
        assert analyzer._days_since(stub["modified"]) is None
        assert analyzer.neglect_multiplier(None) == 1.0

    def test_listed_posts_are_not_duplicated_as_stubs(self, monkeypatch, fake_wp):
        fake_wp(posts=[wp_item(7)], pages=[])
        monkeypatch.setattr(
            wp_client,
            "fetch_rankmath_scores",
            lambda **kw: {
                7: {
                    "id": 7,
                    "seo_score": 12,
                    "url": "https://example.com/post-7/",
                    "modified": "2019-01-01T00:00:00",
                }
            },
        )

        out = wp_client.list_content_with_rankmath(per_type_max=50)

        assert [p["id"] for p in out] == [7]
        assert out[0]["rankmath"]["seo_score"] == 12

    def test_stub_keeps_the_content_type_the_score_endpoint_reported(
        self, monkeypatch, fake_wp
    ):
        """A scored page must not be relabelled a post on the way through."""
        fake_wp(posts=[], pages=[])
        monkeypatch.setattr(
            wp_client,
            "fetch_rankmath_scores",
            lambda **kw: {
                9: {
                    "id": 9,
                    "seo_score": 40,
                    "url": "https://example.com/a-page/",
                    "type": "page",
                }
            },
        )

        assert wp_client.list_content_with_rankmath(per_type_max=50)[0][
            "type"
        ] == "page"
