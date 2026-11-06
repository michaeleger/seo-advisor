"""
Rank Math score reconciliation between selection and Stage 2b.

Selection reads the WordPress catalog. When the catalog misses a page, the
page is selected with an unknown score — but Stage 2b then fetches the page
itself and finds one. Nothing copied it back, so the 2026-09-10 report
carried `score=10/100 (unknown RankMath score)`: a number and a label saying
there is no number, about the same page. The page's fixability was also
computed from "unknown" (1.3) rather than from 10 (1.9).
"""
from __future__ import annotations

import analyzer
import config
import wp_client


def metrics_for(score=None, **over):
    """A selected page as select_pages emits it."""
    base = {
        "page": "https://example.com/p/",
        "clicks": 2, "impressions": 400, "ctr": 0.005, "position": 18.0,
        "missed_clicks": 10.0,
        "neglect_multiplier": 2.0,
        "decay_multiplier": 1.5,
    }
    base.update(analyzer.resolve_rankmath(score))
    base["priority"] = (
        base["missed_clicks"]
        * base["neglect_multiplier"]
        * base["fixability_multiplier"]
        * base["decay_multiplier"]
    )
    base.update(over)
    return base


def post_with(score):
    return {
        "id": 1, "title": "A Post", "url": "https://example.com/p/",
        "content_plain": "", "rankmath": {"seo_score": score},
    }


class TestResolveRankmath:
    def test_unknown_score_keeps_the_unknown_tier(self):
        out = analyzer.resolve_rankmath(None)
        assert out["rankmath_score"] is None
        assert out["rankmath_tier"] == 5
        assert out["rankmath_tier_label"] == "unknown RankMath score"

    def test_score_and_label_always_agree(self):
        for score, label in ((10, "under 20 (critical)"), (85, "80+ (strong)")):
            out = analyzer.resolve_rankmath(score)
            assert out["rankmath_score"] == score
            assert out["rankmath_tier_label"] == label

    def test_fixability_rises_as_the_score_falls(self):
        assert analyzer.fixability_multiplier(10) > analyzer.fixability_multiplier(80)

    def test_unknown_score_sits_between_the_extremes(self):
        """Not knowing is not evidence that there is nothing to fix."""
        unknown = analyzer.fixability_multiplier(None)
        assert analyzer.fixability_multiplier(90) < unknown
        assert unknown < analyzer.fixability_multiplier(10)


class TestSyncFromPost:
    def test_unknown_plus_post_score_becomes_consistent(self):
        """The 2026-09-10 shape: metrics say unknown, the post says 10."""
        m = metrics_for(None)
        assert m["rankmath_tier_label"] == "unknown RankMath score"

        analyzer.sync_rankmath_from_post(m, post_with(10))

        assert m["rankmath_score"] == 10
        assert m["rankmath_tier"] == wp_client.score_tier(10)
        assert m["rankmath_tier_label"] == "under 20 (critical)"
        assert "unknown" not in m["rankmath_tier_label"]

    def test_fixability_is_recomputed_from_the_real_score(self):
        m = metrics_for(None)
        analyzer.sync_rankmath_from_post(m, post_with(10))
        assert m["fixability_multiplier"] == analyzer.fixability_multiplier(10)

    def test_priority_is_recomputed_from_the_stored_multipliers(self):
        m = metrics_for(None)
        analyzer.sync_rankmath_from_post(m, post_with(10))
        assert m["priority"] == (
            m["missed_clicks"]
            * m["neglect_multiplier"]
            * m["fixability_multiplier"]
            * m["decay_multiplier"]
        )

    def test_the_post_wins_a_disagreement(self):
        m = metrics_for(70)
        analyzer.sync_rankmath_from_post(m, post_with(10))
        assert m["rankmath_score"] == 10
        assert m["rankmath_tier_label"] == "under 20 (critical)"

    def test_no_post_score_changes_nothing(self):
        m = metrics_for(70)
        before = dict(m)
        analyzer.sync_rankmath_from_post(m, post_with(None))
        assert m == before

    def test_missing_post_entirely_changes_nothing(self):
        m = metrics_for(None)
        before = dict(m)
        analyzer.sync_rankmath_from_post(m, None)
        analyzer.sync_rankmath_from_post(m, {})
        assert m == before

    def test_agreement_is_a_no_op(self):
        m = metrics_for(40)
        before = dict(m)
        analyzer.sync_rankmath_from_post(m, post_with(40))
        assert m == before

    def test_reasons_are_resynced_to_the_post_score(self):
        """R2: the reason line must not keep quoting the catalog's score."""
        m = metrics_for(70, reasons=[
            "~12 clicks/yr lost to weak CTR for its position (18.0)",
            "RankMath 70/100 — 60–79 (good — still improvable)",
        ])
        analyzer.sync_rankmath_from_post(m, post_with(10))
        assert m["reasons"] == [
            "~12 clicks/yr lost to weak CTR for its position (18.0)",
            "RankMath 10/100 — under 20 (critical)",
        ]

    def test_reason_is_added_when_selection_had_no_score(self):
        m = metrics_for(None, reasons=["Low traffic opportunity"])
        analyzer.sync_rankmath_from_post(m, post_with(10))
        assert m["reasons"] == ["RankMath 10/100 — under 20 (critical)"]

    def test_selection_order_is_not_disturbed(self):
        """Syncing corrects the numbers; it does not re-rank a chosen run."""
        low, high = metrics_for(None, missed_clicks=1.0), metrics_for(None)
        selected = [low, high]
        for m in selected:
            analyzer.sync_rankmath_from_post(m, post_with(10))
        assert selected == [low, high]


class TestLateHighScore:
    """A score arriving after selection that would have skipped the page."""

    def test_the_page_keeps_its_corrected_score_in_this_run(self):
        m = metrics_for(None)
        analyzer.sync_rankmath_from_post(m, post_with(85))
        assert m["rankmath_score"] == 85
        assert m["rankmath_tier_label"] == "80+ (strong)"
        assert m["fixability_multiplier"] == analyzer.fixability_multiplier(85)

    def test_the_next_run_skips_it_once_the_score_is_in_the_catalog(self, gsc_row, wp_post):
        """Documented behaviour: the skip applies at selection, not mid-run."""
        url = "https://example.com/p/"
        assert config.RANKMATH_SKIP_SCORE == 80

        unknown = analyzer.select_pages([gsc_row(url)], wp_posts=[])
        assert [c["page"] for c in unknown["selected"]] == [url]

        known = analyzer.select_pages(
            [gsc_row(url)], wp_posts=[wp_post(url, score=85)]
        )
        assert known["selected"] == []
