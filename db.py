"""Persistent state for SEO Advisor: page history, cooldown tracking, delta metrics."""
import json
import sqlite3
from datetime import date, timedelta

DB_PATH = "seo_state.db"


def init_db() -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS page_history (
                url              TEXT PRIMARY KEY,
                last_analyzed    TEXT NOT NULL,
                last_metrics     TEXT NOT NULL,
                report_file      TEXT
            )
        """)


def get_page_state(url: str) -> dict | None:
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            "SELECT last_analyzed, last_metrics, report_file FROM page_history WHERE url=?",
            (url,),
        ).fetchone()
    if not row:
        return None
    return {
        "last_analyzed": row[0],
        "last_metrics": json.loads(row[1]),
        "report_file": row[2],
    }


def save_page_state(url: str, metrics: dict, report_file: str) -> None:
    metrics_clean = {k: v for k, v in metrics.items() if k != "reasons"}
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """INSERT OR REPLACE INTO page_history (url, last_analyzed, last_metrics, report_file)
               VALUES (?, ?, ?, ?)""",
            (url, date.today().isoformat(), json.dumps(metrics_clean), report_file),
        )


def cooldown_urls(all_metrics: list[dict], cooldown_days: int) -> set[str]:
    """Return the set of URLs that were analyzed within the cooldown window."""
    cutoff = (date.today() - timedelta(days=cooldown_days)).isoformat()
    excluded = set()
    with sqlite3.connect(DB_PATH) as conn:
        for row in all_metrics:
            url = row["page"]
            result = conn.execute(
                "SELECT last_analyzed FROM page_history WHERE url=?", (url,)
            ).fetchone()
            if result and result[0] >= cutoff:
                excluded.add(url)
    return excluded
