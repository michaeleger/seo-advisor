"""
Persistent state: page history, edit-aware backoff, delta metrics.

The backoff model matters. A page suggested but not edited is NOT a page you
rejected — it is a page you had no capacity for. So it is deferred and
returns, never dropped, and its priority score is untouched while it waits.
Only the eligibility window moves, and the backoff is capped so exponential
delay never silently becomes deletion.
"""
import json
import sqlite3
from datetime import date, timedelta

import config

DB_PATH = "seo_state.db"


def _connect():
    return sqlite3.connect(DB_PATH)


def init_db() -> None:
    with _connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS page_history (
                url              TEXT PRIMARY KEY,
                last_analyzed    TEXT NOT NULL,
                last_metrics     TEXT NOT NULL,
                report_file      TEXT
            )
        """)
        # Additive migration — existing rows keep their history.
        existing = {r[1] for r in conn.execute("PRAGMA table_info(page_history)")}
        for column, ddl in (
            ("last_modified_seen", "TEXT"),
            ("times_suggested", "INTEGER NOT NULL DEFAULT 0"),
            ("defer_until", "TEXT"),
        ):
            if column not in existing:
                conn.execute(f"ALTER TABLE page_history ADD COLUMN {column} {ddl}")


def get_page_state(url: str) -> dict | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT last_analyzed, last_metrics, report_file, last_modified_seen, "
            "times_suggested, defer_until FROM page_history WHERE url=?",
            (url,),
        ).fetchone()
    if not row:
        return None
    return {
        "last_analyzed": row[0],
        "last_metrics": json.loads(row[1]),
        "report_file": row[2],
        "last_modified_seen": row[3],
        "times_suggested": row[4] or 0,
        "defer_until": row[5],
    }


def get_all_states() -> dict[str, dict]:
    """Whole history in one read — the table is small and callers want it all."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT url, last_analyzed, last_metrics, report_file, "
            "last_modified_seen, times_suggested, defer_until FROM page_history"
        ).fetchall()
    out = {}
    for url, analyzed, metrics, report_file, modified_seen, times, defer in rows:
        try:
            parsed = json.loads(metrics)
        except (TypeError, ValueError):
            parsed = {}
        out[url] = {
            "last_analyzed": analyzed,
            "last_metrics": parsed,
            "report_file": report_file,
            "last_modified_seen": modified_seen,
            "times_suggested": times or 0,
            "defer_until": defer,
        }
    return out


def backoff_days(times_suggested: int) -> int:
    """
    Days to defer after being suggested `times_suggested` times without an
    edit. The final value is a cap, not a step — a page always comes back.
    """
    schedule = config.BACKOFF_DAYS or (30, 60, 90, 180)
    idx = max(1, int(times_suggested)) - 1
    return int(schedule[min(idx, len(schedule) - 1)])


def save_page_state(
    url: str,
    metrics: dict,
    report_file: str,
    *,
    wp_modified: str | None = None,
    times_suggested: int = 1,
    defer_days: int | None = None,
) -> None:
    """Record a suggestion and set the window before this page may return."""
    metrics_clean = {k: v for k, v in metrics.items() if k != "reasons"}
    if defer_days is None:
        defer_days = backoff_days(times_suggested)
    defer_until = (date.today() + timedelta(days=defer_days)).isoformat()
    with _connect() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO page_history
               (url, last_analyzed, last_metrics, report_file,
                last_modified_seen, times_suggested, defer_until)
               VALUES (?,?,?,?,?,?,?)""",
            (
                url,
                date.today().isoformat(),
                json.dumps(metrics_clean),
                report_file,
                wp_modified,
                int(times_suggested),
                defer_until,
            ),
        )


def mark_edited(url: str, wp_modified: str) -> None:
    """
    The page changed since we last suggested it — capacity arrived and it got
    attention. Reset the backoff and hold it for a re-rank period, because a
    fix cannot be judged before Google has reprocessed the page.
    """
    defer_until = (
        date.today() + timedelta(days=config.EDIT_COOLDOWN_DAYS)
    ).isoformat()
    with _connect() as conn:
        conn.execute(
            """UPDATE page_history
               SET last_modified_seen=?, times_suggested=0, defer_until=?
               WHERE url=?""",
            (wp_modified, defer_until, url),
        )


def cooldown_urls(all_metrics: list[dict], cooldown_days: int) -> set[str]:
    """
    Back-compat: URLs analyzed within a flat window.

    Superseded by defer_until, which the analyzer reads directly. Kept because
    it is a clearer answer to "was this reported recently" than reading the
    backoff state.
    """
    cutoff = (date.today() - timedelta(days=cooldown_days)).isoformat()
    wanted = {row["page"] for row in all_metrics if row.get("page")}
    if not wanted:
        return set()
    with _connect() as conn:
        recent = {
            url
            for (url,) in conn.execute(
                "SELECT url FROM page_history WHERE last_analyzed >= ?", (cutoff,)
            )
        }
    return wanted & recent
