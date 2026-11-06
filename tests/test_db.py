"""Cooldown state."""
from __future__ import annotations

import json
import sqlite3
from datetime import date, timedelta

import pytest

import analyzer
import db


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    path = tmp_path / "state.db"
    monkeypatch.setattr(db, "DB_PATH", str(path))
    db.init_db()
    return path


def seed(path, url, days_ago):
    when = (date.today() - timedelta(days=days_ago)).isoformat()
    with sqlite3.connect(str(path)) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO page_history "
            "(url, last_analyzed, last_metrics, report_file) VALUES (?,?,?,?)",
            (url, when, json.dumps({"clicks": 1}), "r.md"),
        )


class TestCooldownUrls:
    def test_recent_urls_are_excluded_and_old_ones_are_not(self, temp_db):
        seed(temp_db, "https://e.com/recent/", days_ago=5)
        seed(temp_db, "https://e.com/old/", days_ago=90)
        rows = [{"page": "https://e.com/recent/"}, {"page": "https://e.com/old/"}]

        assert db.cooldown_urls(rows, 60) == {"https://e.com/recent/"}

    def test_boundary_day_is_still_in_cooldown(self, temp_db):
        seed(temp_db, "https://e.com/edge/", days_ago=60)
        assert db.cooldown_urls([{"page": "https://e.com/edge/"}], 60) == {
            "https://e.com/edge/"
        }

    def test_history_entries_not_in_the_candidate_set_are_ignored(self, temp_db):
        """Only URLs actually up for selection may be returned."""
        seed(temp_db, "https://e.com/other/", days_ago=1)
        assert db.cooldown_urls([{"page": "https://e.com/mine/"}], 60) == set()

    def test_empty_input(self, temp_db):
        assert db.cooldown_urls([], 60) == set()

    def test_rows_without_a_page_key_are_skipped(self, temp_db):
        assert db.cooldown_urls([{"clicks": 1}], 60) == set()

    def test_scales_to_a_large_candidate_set(self, temp_db):
        """Pagination can hand this tens of thousands of pages."""
        seed(temp_db, "https://e.com/p-500/", days_ago=1)
        rows = [{"page": f"https://e.com/p-{i}/"} for i in range(25_000)]
        assert db.cooldown_urls(rows, 60) == {"https://e.com/p-500/"}


class TestPageState:
    def test_round_trip_drops_reasons(self, temp_db):
        db.save_page_state(
            "https://e.com/p/",
            {"clicks": 3, "impressions": 30, "reasons": ["noise"]},
            "report.md",
        )
        state = db.get_page_state("https://e.com/p/")
        assert state["last_metrics"] == {"clicks": 3, "impressions": 30}
        assert state["report_file"] == "report.md"

    def test_missing_url_returns_none(self, temp_db):
        assert db.get_page_state("https://e.com/nope/") is None

    def test_save_is_idempotent(self, temp_db):
        for n in (1, 2):
            db.save_page_state("https://e.com/p/", {"clicks": n}, "r.md")
        assert db.get_page_state("https://e.com/p/")["last_metrics"] == {"clicks": 2}


class TestModifiedPreservation:
    """
    B5: a partial save must not erase what a complete save already learned.

    `save_page_state` wrote `last_modified_seen` unconditionally, so any run
    that could not fetch the page (catalog stub, WP fetch failure) stored NULL
    over the real timestamp. The next run then had nothing to compare a fresh
    `modified` against, and edit detection could never fire — the backoff
    reset that rewards editing a page was unreachable.
    """

    def test_stub_save_does_not_wipe_a_known_timestamp(self, temp_db):
        db.save_page_state(
            "https://e.com/p/", {"clicks": 1}, "r1.md",
            wp_modified="2026-01-02T03:04:05",
        )
        db.save_page_state("https://e.com/p/", {"clicks": 2}, "r2.md")

        state = db.get_page_state("https://e.com/p/")
        assert state["last_modified_seen"] == "2026-01-02T03:04:05"
        assert state["last_metrics"] == {"clicks": 2}
        assert state["report_file"] == "r2.md"

    def test_empty_string_is_treated_as_no_value(self, temp_db):
        """Stage 2b's GSC-only stub carries `modified=""`, not None."""
        db.save_page_state(
            "https://e.com/p/", {"clicks": 1}, "r1.md",
            wp_modified="2026-01-02T03:04:05",
        )
        db.save_page_state(
            "https://e.com/p/", {"clicks": 2}, "r2.md", wp_modified="  ",
        )

        assert (
            db.get_page_state("https://e.com/p/")["last_modified_seen"]
            == "2026-01-02T03:04:05"
        )

    def test_a_real_new_timestamp_still_overwrites(self, temp_db):
        db.save_page_state(
            "https://e.com/p/", {"clicks": 1}, "r.md",
            wp_modified="2026-01-02T03:04:05",
        )
        db.save_page_state(
            "https://e.com/p/", {"clicks": 1}, "r.md",
            wp_modified="2026-06-07T08:09:10",
        )

        assert (
            db.get_page_state("https://e.com/p/")["last_modified_seen"]
            == "2026-06-07T08:09:10"
        )

    def test_backoff_fields_survive_a_stub_save(self, temp_db):
        db.save_page_state(
            "https://e.com/p/", {"clicks": 1}, "r.md",
            wp_modified="2026-01-02T03:04:05", times_suggested=3,
        )
        db.save_page_state(
            "https://e.com/p/", {"clicks": 1}, "r.md", times_suggested=4,
        )

        state = db.get_page_state("https://e.com/p/")
        assert state["times_suggested"] == 4
        assert state["defer_until"] == (
            date.today() + timedelta(days=db.backoff_days(4))
        ).isoformat()
        assert state["last_modified_seen"] == "2026-01-02T03:04:05"

    def test_edit_detection_survives_an_intervening_stub_save(self, temp_db):
        """Full save → stub save → the page is edited. It must be detected."""
        url = "https://example.com/post/"
        db.save_page_state(url, {"clicks": 1}, "r1.md",
                           wp_modified="2026-01-02T03:04:05")
        db.save_page_state(url, {"clicks": 1}, "r2.md")  # stub: no modified

        selection = analyzer.select_pages(
            [{"page": url, "clicks": 1, "impressions": 500,
              "ctr": 0.002, "position": 18.0}],
            wp_posts=[{
                "id": 1, "title": "A Post", "url": url,
                "modified": "2026-08-09T10:11:12",
                "rankmath": {"seo_score": 30},
            }],
            page_states=db.get_all_states(),
        )

        assert [e["page"] for e in selection["edited"]] == [url]

    def test_mark_edited_still_resets_the_backoff(self, temp_db):
        db.save_page_state("https://e.com/p/", {"clicks": 1}, "r.md",
                           wp_modified="2026-01-02T03:04:05", times_suggested=3)
        db.mark_edited("https://e.com/p/", "2026-08-09T10:11:12")

        state = db.get_page_state("https://e.com/p/")
        assert state["last_modified_seen"] == "2026-08-09T10:11:12"
        assert state["times_suggested"] == 0
