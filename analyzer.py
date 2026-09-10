"""Identify and prioritize improvable posts: RankMath score tiers + GSC opportunity."""
from __future__ import annotations

import logging
from datetime import date, datetime
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
    """Legacy GSC upside score. Retained as the tiebreak when no score exists."""
    return float(row.get("impressions") or 0) * (
        1.0 - float(row.get("ctr") or 0)
    ) * max(float(row.get("position") or 1), 1.0)


# ── "Most neglected under-performing page" ───────────────────────────────────
# Typical organic CTR by average position. Approximate and industry-wide, used
# only to size the gap between what a page earns and what its ranking should
# earn — not as a target to hit.
_CTR_BY_POSITION = (
    (1, 0.28), (2, 0.15), (3, 0.11), (4, 0.08), (5, 0.07),
    (6, 0.05), (7, 0.04), (8, 0.033), (9, 0.028), (10, 0.025),
    (15, 0.015), (20, 0.010), (30, 0.005), (50, 0.002),
)


def expected_ctr(position: float) -> float:
    """Interpolate the CTR a page at this average position would typically see."""
    pos = max(float(position or 0), 1.0)
    if pos >= _CTR_BY_POSITION[-1][0]:
        return _CTR_BY_POSITION[-1][1]
    prev_p, prev_c = _CTR_BY_POSITION[0]
    for p, c in _CTR_BY_POSITION:
        if pos <= p:
            if p == prev_p:
                return c
            span = (pos - prev_p) / (p - prev_p)
            return prev_c + (c - prev_c) * span
        prev_p, prev_c = p, c
    return _CTR_BY_POSITION[-1][1]


def _days_since(timestamp: str | None) -> float | None:
    """Days since an ISO timestamp (WordPress `modified`)."""
    if not timestamp:
        return None
    text = str(timestamp).strip().replace("Z", "+00:00")
    try:
        when = datetime.fromisoformat(text)
    except ValueError:
        try:
            when = datetime.strptime(text[:10], "%Y-%m-%d")
        except ValueError:
            return None
    if when.tzinfo is not None:
        when = when.replace(tzinfo=None)
    return max(0.0, (datetime.now() - when).total_seconds() / 86400.0)


def neglect_multiplier(days_stale: float | None) -> float:
    """
    1.0 for a page edited today, rising to NEGLECT_MAX_MULTIPLIER once it has
    been untouched for NEGLECT_FULL_DAYS. Unknown edit date is treated as
    neutral rather than punished.
    """
    if days_stale is None:
        return 1.0
    full = max(1, getattr(config, "NEGLECT_FULL_DAYS", 730))
    ceiling = float(getattr(config, "NEGLECT_MAX_MULTIPLIER", 3.0))
    return 1.0 + (ceiling - 1.0) * min(days_stale / full, 1.0)


def missed_clicks(row: dict) -> dict:
    """
    Size the traffic this page is failing to capture, split by cause.

    ctr_gap        ranks adequately but is clicked less than its position
                   warrants — a title/meta problem.
    position_gap   has demand but ranks poorly — a content/authority problem.
    """
    impressions = float(row.get("impressions") or 0)
    if impressions <= 0:
        return {"ctr_gap": 0.0, "position_gap": 0.0, "total": 0.0}

    position = float(row.get("position") or 0) or 100.0
    actual_ctr = float(row.get("ctr") or 0)
    par_ctr = expected_ctr(position)
    target_ctr = expected_ctr(getattr(config, "TARGET_POSITION", 5))

    ctr_gap = impressions * max(0.0, par_ctr - actual_ctr)
    position_gap = impressions * max(0.0, target_ctr - par_ctr)
    return {
        "ctr_gap": ctr_gap,
        "position_gap": position_gap,
        "total": ctr_gap + position_gap,
    }


def priority_score(row: dict, *, days_stale: float | None, score: int | None) -> dict:
    """
    Rank by neglected under-performance rather than by Rank Math score.

    Rank Math measures SEO-form completeness, so a bio page scores ~9 forever
    and structurally outranks every real article. Here it is only a modest
    multiplier: it says how much obvious work is available, not how much the
    page matters.
    """
    missed = missed_clicks(row)
    neglect = neglect_multiplier(days_stale)
    fixability = 1.0 + ((100 - score) / 100.0 if score is not None else 0.3)

    decay = 1.0
    change = row.get("decay_ratio")
    if change is not None and change < 0:
        decay = 1.0 + min(abs(float(change)), 1.0) * 0.5

    return {
        "priority": missed["total"] * neglect * fixability * decay,
        "missed_clicks": missed["total"],
        "missed_ctr_gap": missed["ctr_gap"],
        "missed_position_gap": missed["position_gap"],
        "neglect_multiplier": neglect,
        "fixability_multiplier": fixability,
        "decay_multiplier": decay,
        "days_stale": days_stale,
    }


def _rankmath_reasons(score: int | None, tier: int) -> list[str]:
    if score is None:
        return ["RankMath score unavailable (install Eager RankMath REST plugin)"]
    label = wp_client.tier_label(tier)
    return [f"RankMath SEO score {score}/100 — tier: {label}"]


def _wp_modified(post: dict | None) -> str | None:
    return (post or {}).get("modified") or None


def select_pages(
    page_metrics: list[dict],
    excluded_urls: set[str] | None = None,
    *,
    wp_posts: list[dict] | None = None,
    decay: dict[str, float] | None = None,
    page_states: dict[str, dict] | None = None,
    respect_defer: bool = True,
) -> dict:
    """
    Choose the most neglected under-performing pages.

    Returns {"selected", "deferred", "edited"}.

    Ranking is by neglected under-performance, not by Rank Math score. Rank
    Math measures SEO-form completeness, so site furniture (a bio page, a
    booking page) scores ~9 permanently and would otherwise outrank every real
    article on every run, forever. Here the score is only a modest multiplier.

    Demand is a gate: a page with no impressions is undiscovered rather than
    under-performing, which is a different job. That gate is what keeps
    furniture out without maintaining a slug blocklist.

    A deferred page is one you had no capacity for, not one you rejected — it
    is reported in "deferred" so the backlog stays visible, and it returns
    with its priority intact.
    """
    excluded_urls = excluded_urls or set()
    page_states = page_states or {}
    site = (config.GSC_SITE_URL or "").rstrip("/")
    skip_at = getattr(config, "RANKMATH_SKIP_SCORE", 80)
    min_impressions = getattr(config, "MIN_IMPRESSIONS", 10)
    include_zero = getattr(config, "INCLUDE_ZERO_TRAFFIC_PAGES", False)
    today = date.today().isoformat()

    wp_by_key: dict[str, dict] = {}
    for post in wp_posts or []:
        if post.get("url"):
            wp_by_key[_canonical_key(post["url"])] = post

    decay_by_key: dict[str, float] = {}
    for page, ratio in (decay or {}).items():
        decay_by_key[_canonical_key(page)] = float(ratio)

    best_by_key: dict[str, dict] = {}
    skipped_utility: list[str] = []
    for row in page_metrics:
        page = row["page"]
        if page in excluded_urls or page.rstrip("/") == site:
            continue
        if _is_utility_page(page):
            skipped_utility.append(page)
            continue
        key = _canonical_key(page)
        prev = best_by_key.get(key)
        if prev is None or row["impressions"] > prev["impressions"]:
            best_by_key[key] = row

    if include_zero:
        for post in wp_posts or []:
            url = post.get("url") or ""
            if not url or _is_utility_page(url):
                continue
            key = _canonical_key(url)
            if key in best_by_key:
                continue
            if (post.get("rankmath") or {}).get("seo_score") is None:
                continue
            best_by_key[key] = {
                "page": url, "clicks": 0, "impressions": 0,
                "ctr": 0.0, "position": 0.0, "_from_wp_only": True,
            }

    candidates: list[dict] = []
    deferred: list[dict] = []
    edited: list[dict] = []
    below_floor = 0

    for key, row in best_by_key.items():
        post = wp_by_key.get(key)
        rm = (post or {}).get("rankmath") or {}
        score = rm.get("seo_score")
        page = row["page"]
        state = page_states.get(page) or {}
        modified = _wp_modified(post)

        # Edited since we last suggested it: capacity arrived and it got
        # attention. Hold it for a re-rank period rather than re-judging a
        # fix Google has not reprocessed yet.
        seen = state.get("last_modified_seen")
        if state and seen and modified and modified != seen:
            edited.append({"page": page, "modified": modified,
                           "wp_title": (post or {}).get("title") or ""})
            continue

        if respect_defer and state.get("defer_until") and today < state["defer_until"]:
            deferred.append({
                "page": page,
                "wp_title": (post or {}).get("title") or "",
                "defer_until": state["defer_until"],
                "times_suggested": state.get("times_suggested") or 0,
                "rankmath_score": score,
                "impressions": row.get("impressions") or 0,
            })
            continue

        if score is not None and skip_at is not None and score >= skip_at:
            continue

        # Demand gate.
        if not row.get("_from_wp_only") and (row.get("impressions") or 0) < min_impressions:
            below_floor += 1
            continue

        days_stale = _days_since(modified)
        scoring = priority_score(
            {**row, "decay_ratio": decay_by_key.get(key)},
            days_stale=days_stale,
            score=score,
        )

        reasons: list[str] = []
        if scoring["missed_ctr_gap"] >= 1:
            reasons.append(
                f"~{scoring['missed_ctr_gap']:.0f} clicks/yr lost to weak CTR "
                f"for its position ({row['position']:.1f})"
            )
        if scoring["missed_position_gap"] >= 1:
            reasons.append(
                f"~{scoring['missed_position_gap']:.0f} clicks/yr available by "
                f"ranking better than {row['position']:.1f}"
            )
        if days_stale is not None and days_stale > 180:
            reasons.append(f"Not edited in {days_stale/365:.1f} years")
        if scoring["decay_multiplier"] > 1.0:
            reasons.append("Impressions falling vs the prior window")
        if score is not None:
            reasons.append(
                f"RankMath {score}/100 — {wp_client.tier_label(wp_client.score_tier(score))}"
            )
        if row.get("_from_wp_only"):
            reasons.append("No Search Console traffic yet")
        if not reasons:
            reasons.append("Low traffic opportunity")

        tier = wp_client.score_tier(score)
        candidates.append({
            **row,
            **scoring,
            "reasons": reasons,
            "rankmath_score": score,
            "rankmath_tier": tier,
            "rankmath_tier_label": wp_client.tier_label(tier),
            "focus_keyword": rm.get("focus_keyword") or "",
            "gsc_opportunity": _gsc_opportunity(row),
            "wp_title": (post or {}).get("title") or "",
            "wp_modified": modified,
            "times_suggested": state.get("times_suggested") or 0,
        })

    if skipped_utility:
        log.info(
            "  %d page(s) filtered as non-content (SKIP_* config); -v to list.",
            len(skipped_utility),
        )
        for url in skipped_utility:
            log.debug("    non-content: %s", url)
    if below_floor:
        log.info(
            "  %d page(s) below the demand floor (<%d impressions) — "
            "undiscovered rather than under-performing.",
            below_floor, min_impressions,
        )
    if edited:
        log.info("  %d page(s) edited since last suggested — resting to re-rank.",
                 len(edited))
    if deferred:
        log.info("  %d page(s) deferred (backlog); they return with priority intact.",
                 len(deferred))

    candidates.sort(key=lambda c: -c.get("priority", 0.0))
    deferred.sort(key=lambda d: d.get("defer_until") or "")
    return {
        "selected": candidates[: config.MAX_POSTS_TO_ANALYZE],
        "deferred": deferred,
        "edited": edited,
        "total_eligible": len(candidates),
    }


def identify_low_performers(
    page_metrics: list[dict],
    excluded_urls: set[str] | None = None,
    *,
    wp_posts: list[dict] | None = None,
    **kwargs,
) -> list[dict]:
    """Back-compat wrapper returning only the selected pages."""
    return select_pages(
        page_metrics, excluded_urls, wp_posts=wp_posts, **kwargs
    )["selected"]
