"""
R1: `modified` in two wire formats read as an edit.

wp/v2 serialises `modified` as `2024-03-05T10:00:00`; the mu-plugin returned
the MySQL column, `2024-03-05 10:00:00`. The analyzer compared the strings, so
a page reaching selection through a plugin stub was "edited" on every run —
pulled from selection, mark_edited stored the other format, and the next run
flipped it back. The most neglected pages never got ranked.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

import analyzer
import db
import wp_client

URL = "https://example.com/neglected/"
MYSQL = "2024-03-05 10:00:00"
ISO = "2024-03-05T10:00:00"


def row():
    return {"page": URL, "clicks": 1, "impressions": 800, "ctr": 0.001, "position": 16.0}


def post(modified):
    return {
        "id": 1, "title": "Neglected", "url": URL, "modified": modified,
        "rankmath": {"seo_score": 30},
    }


def state(seen):
    return {"last_modified_seen": seen, "times_suggested": 1, "defer_until": None}


class TestParse:
    def test_both_wire_formats_are_the_same_instant(self):
        assert wp_client.parse_modified(MYSQL) == wp_client.parse_modified(ISO)
        assert wp_client.parse_modified(ISO) == datetime(2024, 3, 5, 10, 0, 0)

    @pytest.mark.parametrize("raw", [MYSQL, ISO, " 2024-03-05T10:00:00 ",
                                     "2024-03-05T10:00:00Z",
                                     "2024-03-05T10:00:00+00:00"])
    def test_normalises_to_one_string(self, raw):
        assert wp_client.normalize_modified(raw) == ISO

    @pytest.mark.parametrize("raw", [None, "", "   "])
    def test_absent_stays_absent(self, raw):
        assert wp_client.normalize_modified(raw) == ""
        assert wp_client.parse_modified(raw) is None

    def test_days_since_reads_the_mysql_format(self):
        assert analyzer._days_since(MYSQL) == pytest.approx(analyzer._days_since(ISO))


class TestEditDetection:
    def test_mysql_stub_vs_iso_seen_is_not_an_edit(self):
        """The regression: same instant, different string → must NOT be edited."""
        out = analyzer.select_pages(
            [row()], wp_posts=[post(MYSQL)], page_states={URL: state(ISO)}
        )
        assert out["edited"] == []
        assert [c["page"] for c in out["selected"]] == [URL]

    def test_iso_stub_vs_mysql_seen_is_not_an_edit(self):
        out = analyzer.select_pages(
            [row()], wp_posts=[post(ISO)], page_states={URL: state(MYSQL)}
        )
        assert out["edited"] == []

    def test_a_real_edit_is_still_detected_across_formats(self):
        out = analyzer.select_pages(
            [row()], wp_posts=[post("2024-06-01 09:30:00")],
            page_states={URL: state(ISO)},
        )
        assert [e["page"] for e in out["edited"]] == [URL]

    def test_no_ping_pong_after_mark_edited(self, tmp_path, monkeypatch):
        """mark_edited stores one format; the next run sees the other."""
        monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "state.db"))
        db.init_db()
        db.save_page_state(URL, {"clicks": 1}, "r.md", wp_modified=ISO)
        db.mark_edited(URL, MYSQL)

        out = analyzer.select_pages(
            [row()], wp_posts=[post(ISO)], page_states=db.get_all_states(),
            respect_defer=False,
        )
        assert out["edited"] == []


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload
        self.status_code = 200
        self.content = b"x"
        self.headers = {"X-WP-TotalPages": "1"}

    def json(self):
        return self._payload

    def raise_for_status(self):
        pass


class TestIngest:
    def test_plugin_endpoint_rows_are_normalised(self, monkeypatch):
        monkeypatch.setattr(
            wp_client, "_session_get",
            lambda url, params=None, timeout=25: FakeResponse({
                "items": [{"id": 5, "seo_score": 12, "url": URL, "modified": MYSQL}],
                "total_pages": 1,
            }),
        )
        by_id = wp_client.fetch_rankmath_scores_via_etbh_endpoint(max_items=10)
        assert by_id[5]["modified"] == ISO

    def test_wp_rest_items_are_normalised(self):
        item = {"id": 1, "title": {"rendered": "T"}, "content": {"rendered": ""},
                "link": URL, "modified": MYSQL}
        assert wp_client._to_post_dict(item)["modified"] == ISO

    def test_stubs_are_normalised(self, monkeypatch):
        monkeypatch.setattr(
            wp_client, "fetch_rankmath_scores",
            lambda **kw: {5: {"id": 5, "seo_score": 12, "url": URL, "modified": MYSQL}},
        )
        monkeypatch.setattr(
            wp_client, "_fetch_type_catalog", lambda endpoint, budget, scores: ([], False)
        )
        out = wp_client.list_content_with_rankmath(per_type_max=10)
        assert out[0]["modified"] == ISO

    def test_plugin_emits_rfc3339(self):
        src = (
            Path(__file__).resolve().parent.parent
            / "wordpress-plugin" / "eager-rankmath-rest.php"
        ).read_text()
        assert "mysql_to_rfc3339($post->post_modified)" in src
        assert "'modified' => $post->post_modified" not in src
