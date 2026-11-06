"""
B2: the search fallback in get_post_content bound the wrong page.

When the exact `?slug=` lookup missed, any search hit whose slug contained, or
was contained by, the wanted slug was accepted — so `classic-chicken-soup`
resolved to `chicken-soup`, and the report paired one page's Search Console
metrics with another page's content and Rank Math score.
"""
from __future__ import annotations

import logging

import pytest

import wp_client


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload
        self.status_code = 200

    def json(self):
        return self._payload

    def raise_for_status(self):
        pass


def item(slug, pid=1):
    return {
        "id": pid, "slug": slug, "title": {"rendered": slug},
        "content": {"rendered": "<p>x</p>"},
        "link": f"https://example.com/{slug}/", "type": "post",
    }


@pytest.fixture
def search_returns(monkeypatch):
    """Exact slug lookups miss; the text search returns `hits`."""
    def _install(*hits):
        calls = []

        def fake_get(url, params=None, timeout=25):
            params = params or {}
            calls.append(params)
            if "slug" in params:
                return FakeResponse([])
            if url.endswith("/posts"):
                return FakeResponse(list(hits))
            return FakeResponse([])

        monkeypatch.setattr(wp_client, "_session_get", fake_get)
        return calls
    return _install


class TestSlugMatch:
    @pytest.mark.parametrize("wanted,candidate", [
        ("classic-chicken-soup", "chicken-soup"),
        ("chicken-soup", "classic-chicken-soup"),
        ("chicken-soup", "chicken-soup-recipe"),
        ("chicken-soup-recipe", "chicken-soup"),
        ("kale", "kale-benefits"),
        ("abs", "abs-2x"),
        ("soup", "soups"),
        ("", "soup"),
    ])
    def test_rejects_anything_but_identity(self, wanted, candidate):
        assert wp_client.slug_match(wanted, candidate) is None

    def test_exact(self):
        assert wp_client.slug_match("Chicken-Soup", "chicken-soup") == "exact"

    @pytest.mark.parametrize("wanted,candidate", [
        ("chicken-soup", "chicken-soup-2"),
        ("chicken-soup-2", "chicken-soup"),
    ])
    def test_wordpress_duplicate_suffix(self, wanted, candidate):
        assert wp_client.slug_match(wanted, candidate) == "duplicate-suffix"


class TestGetPostContent:
    def test_classic_prefix_does_not_bind_to_the_shorter_slug(self, search_returns):
        search_returns(item("chicken-soup"))
        assert wp_client.get_post_content(
            "https://example.com/classic-chicken-soup/"
        ) is None

    def test_shorter_slug_does_not_bind_to_a_longer_one(self, search_returns):
        search_returns(item("classic-chicken-soup"))
        assert wp_client.get_post_content("https://example.com/chicken-soup/") is None

    def test_exact_search_hit_still_binds(self, search_returns):
        search_returns(item("classic-chicken-soup", pid=1), item("chicken-soup", pid=2))
        post = wp_client.get_post_content("https://example.com/chicken-soup/")
        assert post["id"] == 2

    def test_fuzzy_resolution_is_logged(self, search_returns, caplog):
        search_returns(item("chicken-soup-2", pid=7))
        with caplog.at_level(logging.INFO, logger=wp_client.log.name):
            post = wp_client.get_post_content("https://example.com/chicken-soup/")
        assert post["id"] == 7
        assert any(
            "Slug fallback" in r.message and "chicken-soup-2" in r.message
            for r in caplog.records
        )
