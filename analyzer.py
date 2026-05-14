"""Identify low-performing posts from GSC page metrics."""
import config


def _reasons(row: dict) -> list[str]:
    reasons = []
    if row["impressions"] >= config.MIN_IMPRESSIONS and row["ctr"] < config.MAX_CTR:
        reasons.append(
            f"Low CTR ({row['ctr']*100:.1f}% vs {config.MAX_CTR*100:.0f}% threshold)"
        )
    if row["impressions"] >= config.MIN_IMPRESSIONS and row["position"] > config.MAX_POSITION:
        reasons.append(
            f"Weak ranking (avg position {row['position']:.1f})"
        )
    if row["clicks"] < 10 and row["impressions"] >= config.MIN_IMPRESSIONS:
        reasons.append(f"Very low clicks ({int(row['clicks'])} in {config.DATE_RANGE_DAYS} days)")
    return reasons


def _opportunity_score(row: dict) -> float:
    """Higher = worse performer = more to gain. impressions × missed-click-rate × position."""
    return row["impressions"] * (1.0 - row["ctr"]) * row["position"]


def identify_low_performers(
    page_metrics: list[dict],
    excluded_urls: set[str] | None = None,
) -> list[dict]:
    """
    Filter and rank the worst-performing pages by opportunity score.
    Pages in excluded_urls (cooldown) are skipped.
    """
    excluded_urls = excluded_urls or set()
    low = []
    for row in page_metrics:
        page = row["page"]
        if page in excluded_urls:
            continue
        if page.rstrip("/") == config.GSC_SITE_URL.rstrip("/"):
            continue
        if any(seg in page for seg in ["/category/", "/tag/", "/author/", "/page/", "?"]):
            continue

        reasons = _reasons(row)
        if reasons:
            low.append({**row, "reasons": reasons})

    low.sort(key=_opportunity_score, reverse=True)
    return low[: config.MAX_POSTS_TO_ANALYZE]
