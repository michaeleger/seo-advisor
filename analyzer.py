"""Identify and prioritize improvable posts: RankMath score tiers + GSC opportunity."""
from __future__ import annotations

import logging
from urllib.parse import urlparse

import config
import wp_client

log = logging.getLogger(__name__)


def _slug(url: str) -> str:
    path = urlparse(url).path.rstrip("/")
    if not path:
        return ""
    return path.split("/")[-1].lower()


def _is_homepage(url: str) -> bool:
    path = urlparse(url).path.rstrip("/")
    return path == ""


def _is_utility_page(url: str) -> bool:
    """
    True for URLs that are never optimizable article content.

    Filtering is config-driven (see SKIP_* in config.py) so the tool is not
    wired to one site. Note there is deliberately no minimum-slug-length
    rule: it silently dropped legitimate short slugs like /abs/ and /gut/.
    """
    if _is_homepage(url):
        return True
    parsed = urlparse(url)
    if parsed.query:
        return True
    lower = (parsed.path or "/").lower()
    if any(seg in lower for seg in config.SKIP_PATH_SEGMENTS):
        return True
    slug = _slug(url)
    if slug in config.SKIP_SLUGS:
        return True
    if any(part in slug for part in config.SKIP_SLUG_SUBSTRINGS):
        return True
    return False


def _canonical_key(url: str) -> str:
    p = urlparse(url)
    host = (p.netloc or "").lower()
    if host.startswith("www."):
        host = host[4:]
    path = (p.path or "/").rstrip("/").lower() or "/"
    return f"{host}{path}"


def _gsc_reasons(row: dict) -> list[str]:
    reasons = []
    if row["impressions"] >= config.MIN_IMPRESSIONS and row["ctr"] < config.MAX_CTR:
        reasons.append(
            f"Low CTR ({row['ctr']*100:.1f}% vs {config.MAX_CTR*100:.0f}% threshold)"
        )
    if (
        row["impressions"] >= config.MIN_IMPRESSIONS
        and row["position"] > config.MAX_POSITION
    ):
        reasons.append(f"Weak ranking (avg position {row['position']:.1f})")
    if row["clicks"] < 10 and row["impressions"] >= config.MIN_IMPRESSIONS:
        reasons.append(
            f"Very low clicks ({int(row['clicks'])} in {config.DATE_RANGE_DAYS} days)"
        )
    if not reasons and row["impressions"] >= config.MIN_IMPRESSIONS:
        reasons.append(
            f"Low traffic opportunity "
            f"({int(row['impressions'])} impr, {int(row['clicks'])} clicks, "
            f"pos {row['position']:.1f})"
        )
    return reasons


def _gsc_opportunity(row: dict) -> float:
    """Higher = more GSC upside."""
    return float(row.get("impressions") or 0) * (
        1.0 - float(row.get("ctr") or 0)
    ) * max(float(row.get("position") or 1), 1.0)


def _rankmath_reasons(score: int | None, tier: int) -> list[str]:
    if score is None:
        return ["RankMath score unavailable (install Eager RankMath REST plugin)"]
    label = wp_client.tier_label(tier)
    return [f"RankMath SEO score {score}/100 — tier: {label}"]


def identify_low_performers(
    page_metrics: list[dict],
    excluded_urls: set[str] | None = None,
    *,
    wp_posts: list[dict] | None = None,
) -> list[dict]:
    """
    Prioritize pages to work on:

    1) RankMath score tier (most improvable first):
         under 20 → under 40 → under 60 → under 80 → 80+ → unknown
    2) Within a tier, higher GSC opportunity score first
    3) Optionally skip scores at/above RANKMATH_SKIP_SCORE (default 80)
       so energy stays on improvable content

    When RankMath scores are missing, falls back to pure GSC ranking.
    """
    excluded_urls = excluded_urls or set()
    site = (config.GSC_SITE_URL or "").rstrip("/")
    prioritize_rm = getattr(config, "PRIORITIZE_BY_RANKMATH", True)
    skip_at = getattr(config, "RANKMATH_SKIP_SCORE", 80)

    # Index WP posts by canonical URL
    wp_by_key: dict[str, dict] = {}
    for post in wp_posts or []:
        url = post.get("url") or ""
        if not url:
            continue
        wp_by_key[_canonical_key(url)] = post

    # Dedupe GSC rows
    best_by_key: dict[str, dict] = {}
    skipped_utility: list[str] = []
    for row in page_metrics:
        page = row["page"]
        if page in excluded_urls:
            continue
        if page.rstrip("/") == site:
            continue
        if _is_utility_page(page):
            skipped_utility.append(page)
            continue

        key = _canonical_key(page)
        prev = best_by_key.get(key)
        if prev is None or row["impressions"] > prev["impressions"]:
            best_by_key[key] = row

    # Also include WP posts that have poor RankMath but little/no GSC row
    if prioritize_rm and wp_posts:
        for post in wp_posts:
            url = post.get("url") or ""
            if not url or _is_utility_page(url):
                continue
            key = _canonical_key(url)
            if key in best_by_key:
                continue
            score = (post.get("rankmath") or {}).get("seo_score")
            if score is None:
                continue
            if skip_at is not None and score >= skip_at:
                continue
            # Synthetic GSC row so low-score posts still enter the queue
            best_by_key[key] = {
                "page": url,
                "clicks": 0,
                "impressions": 0,
                "ctr": 0.0,
                "position": 0.0,
                "_from_wp_only": True,
            }

    candidates: list[dict] = []
    scores_found = 0
    for key, row in best_by_key.items():
        post = wp_by_key.get(key)
        rm = (post or {}).get("rankmath") or {}
        score = rm.get("seo_score")
        if score is not None:
            scores_found += 1
        tier = wp_client.score_tier(score)

        # Skip already-strong pages when we have a real score
        if (
            prioritize_rm
            and score is not None
            and skip_at is not None
            and score >= skip_at
        ):
            continue

        # GSC thin filter only when not RankMath-driven low score
        if not row.get("_from_wp_only"):
            if row.get("impressions", 0) < config.MIN_IMPRESSIONS and (
                score is None or not prioritize_rm
            ):
                continue

        reasons = []
        if prioritize_rm:
            reasons.extend(_rankmath_reasons(score, tier))
        gsc_r = _gsc_reasons(row) if not row.get("_from_wp_only") else []
        if row.get("_from_wp_only"):
            gsc_r = ["Little/no GSC traffic yet — RankMath priority only"]
        reasons.extend(gsc_r)

        if not reasons:
            continue

        candidates.append(
            {
                **row,
                "reasons": reasons,
                "rankmath_score": score,
                "rankmath_tier": tier,
                "rankmath_tier_label": wp_client.tier_label(tier),
                "focus_keyword": rm.get("focus_keyword") or "",
                "gsc_opportunity": _gsc_opportunity(row),
                "wp_title": (post or {}).get("title") or "",
            }
        )

    def _sort_key(c: dict) -> tuple:
        if prioritize_rm and scores_found > 0:
            # Lower tier first, then lower score, then higher GSC opportunity
            score = c.get("rankmath_score")
            score_sort = score if score is not None else 999
            return (
                c.get("rankmath_tier", 5),
                score_sort,
                -c.get("gsc_opportunity", 0.0),
            )
        return (0, 0, -c.get("gsc_opportunity", 0.0))

    if skipped_utility:
        log.info(
            "  %d page(s) filtered as non-content (SKIP_* config); -v to list.",
            len(skipped_utility),
        )
        for url in skipped_utility:
            log.debug("    non-content: %s", url)

    candidates.sort(key=_sort_key)
    return candidates[: config.MAX_POSTS_TO_ANALYZE]
