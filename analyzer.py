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


def identify_low_performers(page_metrics: list[dict]) -> list[dict]:
    """
    Filter and rank pages that are underperforming.
    Returns a list sorted by opportunity size (highest impressions first,
    so we tackle the posts with the most to gain).
    """
    low = []
    for row in page_metrics:
        # Skip non-post URLs (home page, category/tag archives, etc.)
        page = row["page"]
        if page.rstrip("/") == config.GSC_SITE_URL.rstrip("/"):
            continue
        if any(seg in page for seg in ["/category/", "/tag/", "/author/", "/page/", "?"]):
            continue

        reasons = _reasons(row)
        if reasons:
            low.append({**row, "reasons": reasons})

    # Sort by impressions descending — most visible underperformers first
    low.sort(key=lambda r: r["impressions"], reverse=True)
    return low[: config.MAX_POSTS_TO_ANALYZE]
