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
from analyzer import canonical_key

DB_PATH = str(config.PROJECT_DIR / "seo_state.db")


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
        _rekey_to_canonical(conn)


_COLUMNS = (
    "url", "last_analyzed", "last_metrics", "report_file",
    "last_modified_seen", "times_suggested", "defer_until",
)


def _rekey_to_canonical(conn) -> None:
    """
    Migrate rows keyed by raw URL to canonical_key.

    History written before keys were canonical can hold one page twice
    (`https://www.e.com/p/` and `https://e.com/p`). The most recently analysed
    row wins; a stamp only the older row knew is kept rather than lost — the
    same "absent is not a value" rule save_page_state follows.
    """
    rows = conn.execute(f"SELECT {', '.join(_COLUMNS)} FROM page_history").fetchall()
    groups: dict[str, list[dict]] = {}
    for row in rows:
        record = dict(zip(_COLUMNS, row))
        groups.setdefault(canonical_key(record["url"]), []).append(record)

    for key, records in groups.items():
        if len(records) == 1 and records[0]["url"] == key:
            continue
        records.sort(
            key=lambda r: (r["last_analyzed"] or "", r["times_suggested"] or 0),
            reverse=True,
        )
        merged = dict(records[0], url=key)
        for column in ("report_file", "last_modified_seen", "defer_until"):
            if not merged[column]:
                merged[column] = next(
                    (r[column] for r in records[1:] if r[column]), None
                )
        conn.executemany(
            "DELETE FROM page_history WHERE url=?", [(r["url"],) for r in records]
        )
        conn.execute(
            f"INSERT INTO page_history ({', '.join(_COLUMNS)}) "
            f"VALUES ({', '.join('?' for _ in _COLUMNS)})",
            tuple(merged[c] for c in _COLUMNS),
        )


def get_page_state(url: str) -> dict | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT last_analyzed, last_metrics, report_file, last_modified_seen, "
            "times_suggested, defer_until FROM page_history WHERE url=?",
            (canonical_key(url),),
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
    """
    Whole history in one read — the table is small and callers want it all.

    Keyed by canonical_key, the same identity select_pages looks pages up by.
    """
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
    """
    Record a suggestion and set the window before this page may return.

    An absent `wp_modified` means "we did not learn an edit date this run" —
    a catalog stub, a WP fetch that failed — not "this page has no edit date".
    An INSERT OR REPLACE wrote NULL over the stored stamp, so the next run had
    nothing to compare against and edit detection could never fire. Upsert and
    COALESCE instead: a missing value leaves what we already knew alone.
    """
    metrics_clean = {k: v for k, v in metrics.items() if k != "reasons"}
    if defer_days is None:
        defer_days = backoff_days(times_suggested)
    defer_until = (date.today() + timedelta(days=defer_days)).isoformat()
    modified = (wp_modified or "").strip() or None
    with _connect() as conn:
        conn.execute(
            """INSERT INTO page_history
               (url, last_analyzed, last_metrics, report_file,
                last_modified_seen, times_suggested, defer_until)
               VALUES (?,?,?,?,?,?,?)
               ON CONFLICT(url) DO UPDATE SET
                 last_analyzed      = excluded.last_analyzed,
                 last_metrics       = excluded.last_metrics,
                 report_file        = COALESCE(excluded.report_file,
                                               page_history.report_file),
                 last_modified_seen = COALESCE(excluded.last_modified_seen,
                                               page_history.last_modified_seen),
                 times_suggested    = excluded.times_suggested,
                 defer_until        = excluded.defer_until""",
            (
                canonical_key(url),
                date.today().isoformat(),
                json.dumps(metrics_clean),
                report_file,
                modified,
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
            (wp_modified, defer_until, canonical_key(url)),
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
            canonical_key(url)
            for (url,) in conn.execute(
                "SELECT url FROM page_history WHERE last_analyzed >= ?", (cutoff,)
            )
        }
    return {page for page in wanted if canonical_key(page) in recent}
