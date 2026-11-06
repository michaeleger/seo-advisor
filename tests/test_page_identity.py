"""
B1: one canonical page identity for dedup, state lookup and persistence.

Selection deduplicated pages by canonical key but looked state up by the raw
Search Console URL, and the database stored whatever URL it was handed. The
same page under `www.` or without its trailing slash therefore had no history:
its backoff never applied and its edits were never detected.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import date, timedelta

import pytest

import analyzer
import db

VARIANTS = (
    "https://www.example.com/kale-benefits/",
    "https://example.com/kale-benefits",
    "https://example.com/kale-benefits/",
    "http://WWW.example.com/Kale-Benefits",
)


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    path = tmp_path / "state.db"
    monkeypatch.setattr(db, "DB_PATH", str(path))
    db.init_db()
    return path


def urls_in(path):
    with sqlite3.connect(str(path)) as conn:
        return sorted(u for (u,) in conn.execute("SELECT url FROM page_history"))


class TestCanonicalKey:
    def test_variants_share_one_key(self):
        assert {analyzer.canonical_key(u) for u in VARIANTS} == {
            "example.com/kale-benefits"
        }

    @pytest.mark.parametrize("url", VARIANTS + ("https://example.com/",))
    def test_is_idempotent(self, url):
        key = analyzer.canonical_key(url)
        assert analyzer.canonical_key(key) == key

    def test_legacy_alias_is_the_same_function(self):
        assert analyzer._canonical_key is analyzer.canonical_key


class TestPersistence:
    def test_www_and_trailing_slash_variants_share_state(self, temp_db):
        db.save_page_state(VARIANTS[0], {"clicks": 1}, "r.md",
                           wp_modified="2026-01-02T03:04:05", times_suggested=2)

        for variant in VARIANTS:
            state = db.get_page_state(variant)
            assert state is not None, variant
            assert state["times_suggested"] == 2

        assert urls_in(temp_db) == ["example.com/kale-benefits"]

    def test_saving_under_another_variant_updates_the_same_row(self, temp_db):
        db.save_page_state(VARIANTS[0], {"clicks": 1}, "r1.md", times_suggested=1)
        db.save_page_state(VARIANTS[1], {"clicks": 2}, "r2.md", times_suggested=2)

        assert urls_in(temp_db) == ["example.com/kale-benefits"]
        assert db.get_page_state(VARIANTS[2])["last_metrics"] == {"clicks": 2}

    def test_mark_edited_through_a_variant(self, temp_db):
        db.save_page_state(VARIANTS[0], {"clicks": 1}, "r.md", times_suggested=3)
        db.mark_edited(VARIANTS[1], "2026-08-09T10:11:12")

        state = db.get_page_state(VARIANTS[2])
        assert state["times_suggested"] == 0
        assert state["last_modified_seen"] == "2026-08-09T10:11:12"

    def test_cooldown_matches_across_variants(self, temp_db):
        db.save_page_state(VARIANTS[0], {"clicks": 1}, "r.md")
        assert db.cooldown_urls([{"page": VARIANTS[1]}], 60) == {VARIANTS[1]}


class TestLegacyMigration:
    def _insert(self, path, url, analyzed, seen=None, times=0, defer=None):
        with sqlite3.connect(str(path)) as conn:
            conn.execute(
                "INSERT INTO page_history (url, last_analyzed, last_metrics, "
                "report_file, last_modified_seen, times_suggested, defer_until) "
                "VALUES (?,?,?,?,?,?,?)",
                (url, analyzed, json.dumps({"from": url}), "r.md", seen, times, defer),
            )

    def test_duplicate_raw_rows_merge_into_one_canonical_row(self, temp_db):
        self._insert(temp_db, VARIANTS[0], "2026-01-01",
                     seen="2025-12-01T00:00:00", times=1)
        self._insert(temp_db, VARIANTS[1], "2026-05-01", seen=None, times=3,
                     defer="2026-11-01")

        db.init_db()

        assert urls_in(temp_db) == ["example.com/kale-benefits"]
        state = db.get_page_state(VARIANTS[2])
        # Most recent row wins …
        assert state["last_analyzed"] == "2026-05-01"
        assert state["times_suggested"] == 3
        assert state["defer_until"] == "2026-11-01"
        # … but a stamp only the older row knew is not thrown away.
        assert state["last_modified_seen"] == "2025-12-01T00:00:00"

    def test_migration_is_a_no_op_on_canonical_rows(self, temp_db):
        db.save_page_state(VARIANTS[0], {"clicks": 1}, "r.md")
        before = db.get_all_states()
        db.init_db()
        assert db.get_all_states() == before


class TestSelectionUsesTheSameIdentity:
    def test_deferral_saved_under_www_applies_to_the_non_www_gsc_row(
        self, temp_db, gsc_row, wp_post
    ):
        db.save_page_state(VARIANTS[0], {"clicks": 1}, "r.md", times_suggested=1)

        out = analyzer.select_pages(
            [gsc_row(VARIANTS[1], impressions=1000, ctr=0.001)],
            wp_posts=[wp_post(VARIANTS[2], score=30)],
            page_states=db.get_all_states(),
        )

        assert out["selected"] == []
        assert [d["page"] for d in out["deferred"]] == [VARIANTS[1]]
        assert out["deferred"][0]["defer_until"] == (
            date.today() + timedelta(days=db.backoff_days(1))
        ).isoformat()

    def test_edit_detected_across_variants(self, temp_db, gsc_row, wp_post):
        db.save_page_state(VARIANTS[0], {"clicks": 1}, "r.md",
                           wp_modified="2026-01-02T03:04:05")

        out = analyzer.select_pages(
            [gsc_row(VARIANTS[1], impressions=1000, ctr=0.001)],
            wp_posts=[dict(wp_post(VARIANTS[2], score=30),
                           modified="2026-08-09T10:11:12")],
            page_states=db.get_all_states(),
        )

        assert [e["page"] for e in out["edited"]] == [VARIANTS[1]]

    def test_raw_keyed_state_dicts_still_resolve(self, gsc_row, wp_post):
        future = (date.today() + timedelta(days=20)).isoformat()
        out = analyzer.select_pages(
            [gsc_row(VARIANTS[1], impressions=1000, ctr=0.001)],
            wp_posts=[wp_post(VARIANTS[1], score=30)],
            page_states={VARIANTS[0]: {"defer_until": future, "times_suggested": 1}},
        )
        assert [d["page"] for d in out["deferred"]] == [VARIANTS[1]]

    def test_exclusion_matches_across_variants(self, gsc_row, wp_post):
        out = analyzer.select_pages(
            [gsc_row(VARIANTS[1], impressions=1000, ctr=0.001)],
            excluded_urls={VARIANTS[0]},
            wp_posts=[wp_post(VARIANTS[1], score=30)],
        )
        assert out["selected"] == []
