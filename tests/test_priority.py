"""
Neglect-based priority and the backoff queue.

Two ideas under test:

  Priority  = "most neglected under-performing page", where under-performance
              is measured in clicks being left on the table, not in Rank Math
              form-completeness.
  Backoff   = a page you did not get to is a page you had no capacity for. It
              is deferred and returns with its priority intact. It is never
              dropped, and the schedule is capped so backoff cannot quietly
              become deletion.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

import analyzer
import db

BASE = "https://example.com"


def days_ago(n):
    return (datetime.now() - timedelta(days=n)).isoformat()


def pages(result):
    return [r["page"] for r in result["selected"]]


class TestExpectedCtr:
    def test_better_positions_expect_more_clicks(self):
        assert analyzer.expected_ctr(1) > analyzer.expected_ctr(5)
        assert analyzer.expected_ctr(5) > analyzer.expected_ctr(20)

    def test_curve_is_monotonic(self):
        prev = 1.0
        for pos in range(1, 60):
            cur = analyzer.expected_ctr(pos)
            assert cur <= prev + 1e-9, pos
            prev = cur

    def test_out_of_range_positions_are_clamped(self):
        assert analyzer.expected_ctr(0) == analyzer.expected_ctr(1)
        assert analyzer.expected_ctr(999) > 0


class TestNeglectMultiplier:
    def test_fresh_page_is_unweighted(self):
        assert analyzer.neglect_multiplier(0) == 1.0

    def test_grows_with_staleness_and_is_capped(self, pinned_config):
        cap = pinned_config.NEGLECT_MAX_MULTIPLIER
        assert analyzer.neglect_multiplier(365) > 1.0
        assert analyzer.neglect_multiplier(pinned_config.NEGLECT_FULL_DAYS) == cap
        assert analyzer.neglect_multiplier(99_999) == cap

    def test_unknown_edit_date_is_neutral_not_punished(self):
        assert analyzer.neglect_multiplier(None) == 1.0


class TestMissedClicks:
    def test_no_impressions_means_nothing_missed(self):
        assert analyzer.missed_clicks({"impressions": 0})["total"] == 0

    def test_ctr_below_par_for_its_position_is_counted(self):
        m = analyzer.missed_clicks({"impressions": 1000, "ctr": 0.001, "position": 3})
        assert m["ctr_gap"] > 0

    def test_page_already_beating_its_position_has_no_ctr_gap(self):
        m = analyzer.missed_clicks({"impressions": 1000, "ctr": 0.90, "position": 3})
        assert m["ctr_gap"] == 0

    def test_poor_ranking_shows_up_as_position_upside(self):
        deep = analyzer.missed_clicks({"impressions": 1000, "ctr": 0.005, "position": 25})
        shallow = analyzer.missed_clicks({"impressions": 1000, "ctr": 0.005, "position": 4})
        assert deep["position_gap"] > shallow["position_gap"]


class TestPriorityRanking:
    def test_stale_page_outranks_a_fresh_one_with_equal_opportunity(
        self, gsc_row, wp_post
    ):
        stale, fresh = f"{BASE}/stale/", f"{BASE}/fresh/"
        rows = [gsc_row(fresh, impressions=1000, ctr=0.001, position=15.0),
                gsc_row(stale, impressions=1000, ctr=0.001, position=15.0)]
        posts = [dict(wp_post(fresh, score=40), modified=days_ago(5)),
                 dict(wp_post(stale, score=40), modified=days_ago(900))]
        out = analyzer.select_pages(rows, wp_posts=posts)
        assert pages(out) == [stale, fresh]

    def test_declining_impressions_raise_priority(self, gsc_row, wp_post):
        flat, falling = f"{BASE}/flat/", f"{BASE}/falling/"
        rows = [gsc_row(flat, impressions=1000, ctr=0.001, position=15.0),
                gsc_row(falling, impressions=1000, ctr=0.001, position=15.0)]
        posts = [wp_post(flat, score=40), wp_post(falling, score=40)]
        # recent vs preceding window: falling lost 75% of its impressions
        decay = {flat: 0.0, falling: -0.75}
        out = analyzer.select_pages(rows, wp_posts=posts, decay=decay)
        assert pages(out) == [falling, flat]

    def test_reasons_quantify_the_loss(self, gsc_row, wp_post):
        url = f"{BASE}/leaky/"
        out = analyzer.select_pages(
            [gsc_row(url, impressions=5000, ctr=0.001, position=18.0)],
            wp_posts=[dict(wp_post(url, score=30), modified=days_ago(800))],
        )
        reasons = " ".join(out["selected"][0]["reasons"])
        assert "clicks/yr" in reasons
        assert "Not edited in" in reasons


class TestBackoffQueue:
    def _state(self, **over):
        base = {"last_modified_seen": None, "times_suggested": 0, "defer_until": None}
        base.update(over)
        return base

    def test_deferred_page_is_withheld_but_reported_as_backlog(self, gsc_row, wp_post):
        url = f"{BASE}/waiting/"
        future = (date.today() + timedelta(days=20)).isoformat()
        out = analyzer.select_pages(
            [gsc_row(url, impressions=1000, ctr=0.001, position=15.0)],
            wp_posts=[wp_post(url, score=30)],
            page_states={url: self._state(defer_until=future, times_suggested=2)},
        )
        assert out["selected"] == []
        assert len(out["deferred"]) == 1
        assert out["deferred"][0]["times_suggested"] == 2
        assert out["deferred"][0]["defer_until"] == future

    def test_page_returns_once_its_window_passes(self, gsc_row, wp_post):
        url = f"{BASE}/returned/"
        past = (date.today() - timedelta(days=1)).isoformat()
        out = analyzer.select_pages(
            [gsc_row(url, impressions=1000, ctr=0.001, position=15.0)],
            wp_posts=[wp_post(url, score=30)],
            page_states={url: self._state(defer_until=past, times_suggested=3)},
        )
        assert pages(out) == [url]

    def test_priority_is_untouched_by_having_been_deferred(self, gsc_row, wp_post):
        """Passing on a page does not make it less broken."""
        a, b = f"{BASE}/never-seen/", f"{BASE}/seen-thrice/"
        rows = [gsc_row(a, impressions=1000, ctr=0.001, position=15.0),
                gsc_row(b, impressions=1000, ctr=0.001, position=15.0)]
        posts = [wp_post(a, score=40), wp_post(b, score=40)]
        past = (date.today() - timedelta(days=1)).isoformat()
        out = analyzer.select_pages(
            rows, wp_posts=posts,
            page_states={b: self._state(defer_until=past, times_suggested=3)},
        )
        scores = {r["page"]: r["priority"] for r in out["selected"]}
        assert scores[a] == scores[b]

    def test_an_edit_takes_the_page_out_of_rotation_to_re_rank(self, gsc_row, wp_post):
        url = f"{BASE}/edited/"
        out = analyzer.select_pages(
            [gsc_row(url, impressions=1000, ctr=0.001, position=15.0)],
            wp_posts=[dict(wp_post(url, score=30), modified=days_ago(1))],
            page_states={url: self._state(last_modified_seen=days_ago(400),
                                          times_suggested=2)},
        )
        assert out["selected"] == []
        assert [e["page"] for e in out["edited"]] == [url]

    def test_unchanged_page_is_not_treated_as_edited(self, gsc_row, wp_post):
        url = f"{BASE}/untouched/"
        stamp = days_ago(400)
        out = analyzer.select_pages(
            [gsc_row(url, impressions=1000, ctr=0.001, position=15.0)],
            wp_posts=[dict(wp_post(url, score=30), modified=stamp)],
            page_states={url: self._state(last_modified_seen=stamp, times_suggested=2)},
        )
        assert out["edited"] == []
        assert pages(out) == [url]

    def test_no_cooldown_ignores_the_deferral(self, gsc_row, wp_post):
        url = f"{BASE}/forced/"
        future = (date.today() + timedelta(days=20)).isoformat()
        out = analyzer.select_pages(
            [gsc_row(url, impressions=1000, ctr=0.001, position=15.0)],
            wp_posts=[wp_post(url, score=30)],
            page_states={url: self._state(defer_until=future)},
            respect_defer=False,
        )
        assert pages(out) == [url]


class TestBackoffSchedule:
    def test_lengthens_then_caps(self, pinned_config):
        seen = [db.backoff_days(n) for n in range(1, 8)]
        assert seen[:4] == [30, 60, 90, 180]
        assert all(v == 180 for v in seen[3:]), "cap must hold — backoff is not deletion"

    def test_is_never_unbounded(self):
        assert db.backoff_days(10_000) == 180
