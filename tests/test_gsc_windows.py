"""
Period-over-period comparison windows.

The 2026-09-10 report showed pages with `impr 0→N` — growth from nothing —
while the decay signal on the same pages said impressions were falling. Both
came from the same run. The prior window was derived from DATE_RANGE_DAYS
(365), putting its start ~2 years back, outside Search Console's ~16-month
retention: every page had an empty prior half, and an empty prior half reads
as growth.

These tests pin the shape of the windows themselves, so the fix cannot be
undone by someone raising DATE_RANGE_DAYS.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

import briefing
import config
import gsc


def _d(iso: str) -> date:
    return datetime.strptime(iso, "%Y-%m-%d").date()


class TestComparisonWindows:
    def test_previous_ends_the_day_before_current_starts(self):
        (cur_start, _), (_, prev_end), _ = gsc._comparison_ranges()
        assert _d(prev_end) == _d(cur_start) - timedelta(days=1)

    def test_halves_are_equal_length(self):
        (cur_start, cur_end), (prev_start, prev_end), days = gsc._comparison_ranges()
        assert (_d(cur_end) - _d(cur_start)).days == days - 1
        assert (_d(prev_end) - _d(prev_start)).days == days - 1

    def test_current_ends_at_the_data_lag(self):
        (_, cur_end), _, _ = gsc._comparison_ranges()
        assert _d(cur_end) == date.today() - timedelta(days=gsc._DATA_LAG_DAYS)

    def test_prior_start_is_inside_retention_at_365_day_range(self, monkeypatch):
        """The exact configuration that produced the 0→N report."""
        monkeypatch.setattr(config, "DATE_RANGE_DAYS", 365)
        (_, _), (prev_start, _), _ = gsc._comparison_ranges()
        age = (date.today() - _d(prev_start)).days
        assert age <= gsc._RETENTION_DAYS

    def test_prior_window_does_not_follow_date_range_days(self, monkeypatch):
        monkeypatch.setattr(config, "DATE_RANGE_DAYS", 30)
        short = gsc._comparison_ranges()
        monkeypatch.setattr(config, "DATE_RANGE_DAYS", 365)
        long = gsc._comparison_ranges()
        assert short == long

    def test_window_follows_decay_window_days(self, monkeypatch):
        monkeypatch.setattr(config, "DECAY_WINDOW_DAYS", 30)
        assert gsc.comparison_window_days() == 30

    def test_oversized_decay_window_is_clamped_into_retention(self, monkeypatch):
        """A 500-day DECAY_WINDOW_DAYS must not reopen the retention hole."""
        monkeypatch.setattr(config, "DECAY_WINDOW_DAYS", 500)
        (_, _), (prev_start, _), days = gsc._comparison_ranges()
        assert days < 500
        assert (date.today() - _d(prev_start)).days <= gsc._RETENTION_DAYS

    def test_prior_date_range_is_the_adjacent_previous_half(self):
        (_, _), previous, _ = gsc._comparison_ranges()
        assert gsc._prior_date_range() == previous


class FakeQuery:
    """Records request bodies; serves rows only for dates in `has_data`."""

    def __init__(self, has_data=(), impressions=100):
        self.has_data = set(has_data)
        self.impressions = impressions
        self.bodies = []

    def __call__(self, body):
        self.bodies.append(body)
        if body["startDate"] not in self.has_data:
            return []
        return [
            {
                "keys": ["https://example.com/p/"],
                "clicks": 5,
                "impressions": self.impressions,
                "ctr": 0.05,
                "position": 12.0,
            }
        ]


class TestPageComparisonUsesTheHelper:
    def test_queries_the_adjacent_windows(self, monkeypatch):
        (cur_start, cur_end), (prev_start, prev_end), days = gsc._comparison_ranges()
        api = FakeQuery(has_data=(cur_start, prev_start))
        monkeypatch.setattr(gsc, "_query", api)

        out = gsc.get_page_period_comparison("https://example.com/p/")

        assert [(b["startDate"], b["endDate"]) for b in api.bodies] == [
            (cur_start, cur_end),
            (prev_start, prev_end),
        ]
        assert out["current_window"]["days"] == days
        assert out["previous_window"]["days"] == days

    def test_empty_prior_is_not_reported_as_percentage_growth(self, monkeypatch):
        """No prior data is unknown change, not a gain of infinity percent."""
        (cur_start, _), _, _ = gsc._comparison_ranges()
        monkeypatch.setattr(gsc, "_query", FakeQuery(has_data=(cur_start,)))

        out = gsc.get_page_period_comparison("https://example.com/p/")

        assert out["previous_window"]["impressions"] == 0
        assert out["delta"]["impressions_pct"] is None
        assert out["delta"]["clicks_pct"] is None

    def test_markdown_renders_an_empty_prior_as_not_available(self, monkeypatch):
        (cur_start, _), _, _ = gsc._comparison_ranges()
        monkeypatch.setattr(gsc, "_query", FakeQuery(has_data=(cur_start,)))
        period = gsc.get_page_period_comparison("https://example.com/p/")

        post = {
            "id": 1, "title": "P", "url": "https://example.com/p/",
            "content_plain": "", "rankmath": {},
        }
        payload = briefing.build_briefing_payload(
            [{
                "metrics": {"page": post["url"], "clicks": 5, "impressions": 100,
                            "ctr": 0.05, "position": 12.0},
                "post": post,
                "period_comparison": period,
            }],
            site="https://example.com/",
        )
        trend = [
            ln for ln in briefing.briefing_to_markdown(payload).splitlines()
            if "Trend vs prior" in ln
        ]
        assert trend, "expected a trend line"
        assert "(n/a)" in trend[0]
        assert "impr 0→100" in trend[0]


class TestSiteContextDateRange:
    def test_previous_is_adjacent_and_carries_its_own_length(self, monkeypatch):
        monkeypatch.setattr(config, "DATE_RANGE_DAYS", 365)
        monkeypatch.setattr(gsc, "_query", lambda body: [])
        monkeypatch.setattr(gsc, "_query_all", lambda body, **kw: [])

        dr = gsc.get_site_context()["date_range"]

        assert dr["current"]["days"] == 365
        assert dr["previous"]["days"] == gsc.comparison_window_days()
        assert _d(dr["previous"]["end"]) == _d(
            dr["comparison_current"]["start"]
        ) - timedelta(days=1)
        assert (date.today() - _d(dr["previous"]["start"])).days <= gsc._RETENTION_DAYS

    def test_briefing_header_names_the_comparison_pair(self, monkeypatch):
        monkeypatch.setattr(gsc, "_query", lambda body: [])
        monkeypatch.setattr(gsc, "_query_all", lambda body, **kw: [])
        ctx = gsc.get_site_context()

        payload = briefing.build_briefing_payload(
            [], site="https://example.com/", site_context=ctx
        )
        line = [
            ln for ln in briefing.briefing_to_markdown(payload).splitlines()
            if ln.startswith("**Compare vs prior:**")
        ][0]

        assert f"{gsc.comparison_window_days()}d windows" in line
        assert ctx["date_range"]["previous"]["start"] in line
