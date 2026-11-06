"""
B4 — GenerateKeywordIdeasRequest `seed` is a oneof.

keyword_seed, url_seed and keyword_and_url_seed are mutually exclusive.
Setting url_seed after keyword_seed silently cleared the keywords, so a
request with both sent the URL alone. Built against the real proto so the
oneof semantics are Google's, not a mock's.
"""
from __future__ import annotations

import pytest

import keyword_planner

idea_types = pytest.importorskip(
    "google.ads.googleads.v24.services.types.keyword_plan_idea_service"
)
network_types = pytest.importorskip(
    "google.ads.googleads.v24.enums.types.keyword_plan_network"
)

SEED_FIELDS = ("keyword_seed", "url_seed", "keyword_and_url_seed", "site_seed")
URL = "https://example.com/p/"


class _AdsService:
    @staticmethod
    def language_constant_path(i):
        return f"languageConstants/{i}"

    @staticmethod
    def geo_target_constant_path(i):
        return f"geoTargetConstants/{i}"


class _Enums:
    KeywordPlanNetworkEnum = network_types.KeywordPlanNetworkEnum.KeywordPlanNetwork


class FakeClient:
    enums = _Enums

    def get_type(self, name):
        assert name == "GenerateKeywordIdeasRequest"
        return idea_types.GenerateKeywordIdeasRequest()

    def get_service(self, name):
        assert name == "GoogleAdsService"
        return _AdsService()


def build(seeds, page_url):
    request = keyword_planner._build_idea_request(FakeClient(), "123", seeds, page_url)
    pb = type(request).pb(request)
    return request, pb


def _set_members(pb):
    return [f for f in SEED_FIELDS if pb.HasField(f)]


class TestSeedOneof:
    def test_seeds_and_url_use_the_combined_member(self):
        request, pb = build(["gut health", "probiotics"], URL)
        assert _set_members(pb) == ["keyword_and_url_seed"]
        assert list(request.keyword_and_url_seed.keywords) == ["gut health", "probiotics"]
        assert request.keyword_and_url_seed.url == URL

    def test_seeds_only(self):
        request, pb = build(["gut health"], None)
        assert _set_members(pb) == ["keyword_seed"]
        assert list(request.keyword_seed.keywords) == ["gut health"]

    def test_url_only(self):
        request, pb = build([], URL)
        assert _set_members(pb) == ["url_seed"]
        assert request.url_seed.url == URL

    def test_seed_count_capped_at_twenty(self):
        request, _ = build([f"kw{i}" for i in range(30)], URL)
        assert len(request.keyword_and_url_seed.keywords) == 20

    def test_rest_of_request_still_populated(self):
        request, _ = build(["x"], URL)
        assert request.customer_id == "123"
        assert request.language == "languageConstants/1000"
        assert list(request.geo_target_constants)


class TestStillGated:
    def test_unconfigured_makes_no_client(self, monkeypatch):
        # Developer token is optional post-Sep 2026; customer ID is the gate.
        monkeypatch.setattr(keyword_planner.config, "GOOGLE_ADS_CUSTOMER_ID", "")
        monkeypatch.setattr(
            keyword_planner, "_client",
            lambda: pytest.fail("client built while not configured"),
        )
        assert keyword_planner.fetch_keyword_ideas(["x"], page_url=URL) == []
