"""
Selection logic — which pages a run works on.

This is the highest-consequence pure logic in the project: everything
downstream operates on whatever comes out of identify_low_performers, and a
wrong answer here is invisible. You do not get an error, you just quietly
optimize the wrong pages.
"""
from __future__ import annotations

import analyzer

BASE = "https://example.com"


def pages(result):
    return [r["page"] for r in result]


# ── URL filtering ────────────────────────────────────────────────────────────

class TestUtilityPageFiltering:
    def test_homepage_and_structural_paths_are_filtered(self):
        for url in (
            f"{BASE}/",
            f"{BASE}/category/recipes/",
            f"{BASE}/tag/keto/",
            f"{BASE}/author/mike/",
            f"{BASE}/blog/page/2/",
            f"{BASE}/feed/",
        ):
            assert analyzer._is_utility_page(url), url

    def test_generic_non_content_slugs_are_filtered(self):
        for url in (f"{BASE}/about/", f"{BASE}/contact/", f"{BASE}/privacy-policy/"):
            assert analyzer._is_utility_page(url), url

    def test_urls_with_query_strings_are_filtered(self):
        assert analyzer._is_utility_page(f"{BASE}/search/?s=kale")

    def test_short_slugs_are_kept(self):
        """Regression: a `len(slug) < 4` rule silently dropped real articles."""
        for url in (f"{BASE}/abs/", f"{BASE}/gut/", f"{BASE}/ibs/"):
            assert not analyzer._is_utility_page(url), url

    def test_ordinary_article_is_kept(self):
        assert not analyzer._is_utility_page(f"{BASE}/kale-benefits/")

    def test_filtering_follows_config(self, pinned_config, monkeypatch):
        """Site-specific junk comes from config, not from the source."""
        url = f"{BASE}/beaguest/"
        assert not analyzer._is_utility_page(url)
        monkeypatch.setattr(
            pinned_config, "SKIP_SLUGS", pinned_config.SKIP_SLUGS | {"beaguest"}
        )
        assert analyzer._is_utility_page(url)


# ── Deduplication ────────────────────────────────────────────────────────────

class TestCanonicalDedup:
    def test_protocol_host_case_and_slash_variants_collapse(self):
        for url in (
            f"{BASE}/Kale-Benefits/",
            "http://www.example.com/kale-benefits",
            "https://example.com/kale-benefits/",
        ):
            assert analyzer._canonical_key(url) == "example.com/kale-benefits"

    def test_duplicate_rows_keep_the_highest_impressions(self, gsc_row):
        rows = [
            gsc_row("https://www.example.com/kale/", impressions=100, clicks=1),
            gsc_row("https://example.com/kale", impressions=900, clicks=9),
            gsc_row("http://example.com/kale/", impressions=50, clicks=0),
        ]
        out = analyzer.identify_low_performers(rows, wp_posts=[])
        assert len(out) == 1
        assert out[0]["impressions"] == 900


# ── Rank Math prioritization ─────────────────────────────────────────────────

class TestRankMathOrdering:
    def test_lower_tier_sorts_first(self, gsc_row, wp_post):
        urls = {s: f"{BASE}/post-{s}/" for s in (10, 30, 50, 70)}
        rows = [gsc_row(u, impressions=500) for u in urls.values()]
        posts = [wp_post(u, score=s) for s, u in urls.items()]

        out = analyzer.identify_low_performers(rows, wp_posts=posts)

        assert [r["rankmath_score"] for r in out] == [10, 30, 50, 70]

    def test_within_a_tier_higher_gsc_opportunity_wins(self, gsc_row, wp_post):
        low, high = f"{BASE}/low-op/", f"{BASE}/high-op/"
        rows = [
            gsc_row(low, impressions=100, position=5.0),
            gsc_row(high, impressions=5000, position=30.0),
        ]
        # identical score, so only GSC opportunity can separate them
        posts = [wp_post(low, score=25), wp_post(high, score=25)]

        out = analyzer.identify_low_performers(rows, wp_posts=posts)

        assert pages(out) == [high, low]

    def test_score_at_skip_threshold_is_excluded_but_below_is_kept(
        self, gsc_row, wp_post, pinned_config
    ):
        """The boundary, not a midpoint: 80 goes, 79 stays."""
        at, below = f"{BASE}/at-80/", f"{BASE}/at-79/"
        rows = [gsc_row(at, impressions=900), gsc_row(below, impressions=100)]
        posts = [wp_post(at, score=80), wp_post(below, score=79)]

        out = analyzer.identify_low_performers(rows, wp_posts=posts)

        assert pages(out) == [below]

    def test_unscored_pages_sort_after_scored_ones(self, gsc_row, wp_post):
        scored, unscored = f"{BASE}/scored/", f"{BASE}/unscored/"
        rows = [
            gsc_row(unscored, impressions=9000, position=30.0),
            gsc_row(scored, impressions=100, position=5.0),
        ]
        posts = [wp_post(scored, score=45)]

        out = analyzer.identify_low_performers(rows, wp_posts=posts)

        # despite far higher GSC opportunity, the unscored page ranks lower
        assert pages(out) == [scored, unscored]

    def test_falls_back_to_gsc_ranking_when_no_scores_exist(self, gsc_row):
        weak, strong = f"{BASE}/weak/", f"{BASE}/strong/"
        rows = [
            gsc_row(weak, impressions=100, position=5.0),
            gsc_row(strong, impressions=5000, position=30.0),
        ]
        out = analyzer.identify_low_performers(rows, wp_posts=[])
        assert pages(out) == [strong, weak]


# ── WordPress-only rows ──────────────────────────────────────────────────────

class TestWordPressOnlyRows:
    def test_low_score_page_with_no_gsc_data_still_enters_the_queue(self, wp_post):
        url = f"{BASE}/brand-new-post/"
        out = analyzer.identify_low_performers([], wp_posts=[wp_post(url, score=15)])

        assert pages(out) == [url]
        assert out[0]["impressions"] == 0
        assert any("no GSC traffic" in r for r in out[0]["reasons"])

    def test_strong_score_with_no_gsc_data_is_not_queued(self, wp_post):
        out = analyzer.identify_low_performers(
            [], wp_posts=[wp_post(f"{BASE}/already-good/", score=95)]
        )
        assert out == []

    def test_unscored_page_with_no_gsc_data_is_not_queued(self, wp_post):
        """No score and no traffic means no evidence to act on."""
        out = analyzer.identify_low_performers(
            [], wp_posts=[wp_post(f"{BASE}/unknown/", score=None)]
        )
        assert out == []


# ── Thin-traffic filtering ───────────────────────────────────────────────────

class TestThinTrafficFilter:
    def test_thin_row_without_a_score_is_dropped(self, gsc_row, pinned_config):
        rows = [gsc_row(f"{BASE}/thin/", impressions=pinned_config.MIN_IMPRESSIONS - 1)]
        assert analyzer.identify_low_performers(rows, wp_posts=[]) == []

    def test_thin_row_with_a_low_score_is_kept(self, gsc_row, wp_post, pinned_config):
        url = f"{BASE}/thin-but-bad/"
        rows = [gsc_row(url, impressions=pinned_config.MIN_IMPRESSIONS - 1)]
        out = analyzer.identify_low_performers(rows, wp_posts=[wp_post(url, score=15)])
        assert pages(out) == [url]


# ── Cooldown and capping ─────────────────────────────────────────────────────

class TestExclusionAndCap:
    def test_excluded_urls_are_dropped(self, gsc_row):
        kept, skipped = f"{BASE}/kept/", f"{BASE}/skipped/"
        rows = [gsc_row(kept), gsc_row(skipped)]
        out = analyzer.identify_low_performers(rows, excluded_urls={skipped}, wp_posts=[])
        assert pages(out) == [kept]

    def test_cap_applies_after_sorting_so_the_worst_survive(
        self, gsc_row, wp_post, pinned_config, monkeypatch
    ):
        """
        Regression guard: truncating before sorting would keep an arbitrary
        subset. The failure is silent — you just work on the wrong pages.
        """
        monkeypatch.setattr(pinned_config, "MAX_POSTS_TO_ANALYZE", 2)
        urls = {s: f"{BASE}/post-{s}/" for s in (70, 50, 30, 10)}
        rows = [gsc_row(u, impressions=500) for u in urls.values()]
        posts = [wp_post(u, score=s) for s, u in urls.items()]

        out = analyzer.identify_low_performers(rows, wp_posts=posts)

        assert len(out) == 2
        assert [r["rankmath_score"] for r in out] == [10, 30]


# ── Reported fields ──────────────────────────────────────────────────────────

class TestCandidateShape:
    def test_candidate_carries_the_fields_downstream_code_reads(
        self, gsc_row, wp_post
    ):
        url = f"{BASE}/kale/"
        out = analyzer.identify_low_performers(
            [gsc_row(url, impressions=500)],
            wp_posts=[wp_post(url, score=35, focus="kale benefits", title="Kale")],
        )
        c = out[0]
        for field in (
            "page", "clicks", "impressions", "ctr", "position", "reasons",
            "rankmath_score", "rankmath_tier", "rankmath_tier_label",
            "focus_keyword", "gsc_opportunity", "wp_title",
        ):
            assert field in c, field
        assert c["rankmath_score"] == 35
        assert c["focus_keyword"] == "kale benefits"
        assert c["wp_title"] == "Kale"
