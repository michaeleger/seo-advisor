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


def canonical_key(url: str) -> str:
    """
    The one identity for a page: dedup, state lookup and persistence all use it.

    Scheme, `www.`, case and trailing slash are dropped, so Search Console's
    `https://www.example.com/post/` and WordPress's `https://example.com/post`
    are the same page. Three separate notions of identity is how a page's
    backoff and edit history silently failed to follow it between runs.

    Idempotent: a stored key (`example.com/post`) maps to itself, so state
    already keyed this way can be re-keyed without harm.
    """
    text = str(url or "").strip()
    if "://" not in text and not text.startswith("//"):
        text = "//" + text.lstrip("/")
    p = urlparse(text)
    host = (p.netloc or "").lower()
    if host.startswith("www."):
        host = host[4:]
    path = (p.path or "/").rstrip("/").lower() or "/"
    return f"{host}{path}"


_canonical_key = canonical_key


def _states_by_key(page_states: dict[str, dict]) -> dict[str, dict]:
    """
    Re-key page state by canonical_key.

    Legacy history can hold the same page under two spellings; the most
    recently analysed row is the one that reflects the last suggestion.
    """
    out: dict[str, dict] = {}
    for url, state in (page_states or {}).items():
        key = canonical_key(url)
        prev = out.get(key)
        if prev is None or (state.get("last_analyzed") or "") > (
            prev.get("last_analyzed") or ""
        ):
            out[key] = state
    return out


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
    """Days since a WordPress `modified` stamp (ISO or MySQL format)."""
    when = wp_client.parse_modified(timestamp)
    if when is None:
        return None
    return max(0.0, (datetime.now() - when).total_seconds() / 86400.0)


def _modified_changed(seen: str | None, modified: str | None) -> bool:
    """
    True when WordPress reports a different edit time than the one stored.

    Compares instants, not strings: `2024-03-05 10:00:00` (mu-plugin, MySQL)
    and `2024-03-05T10:00:00` (wp/v2) are the same edit, and a string compare
    called that an edit on every run. Only when a side will not parse does
    this fall back to comparing the text.
    """
    if not seen or not modified:
        return False
    seen_at = wp_client.parse_modified(seen)
    modified_at = wp_client.parse_modified(modified)
    if seen_at is not None and modified_at is not None:
        return seen_at != modified_at
    return str(seen).strip() != str(modified).strip()


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


def fixability_multiplier(score: int | None) -> float:
    """
    How much obvious Rank Math work is sitting on the page.

    A score of 10 means almost every mechanical fix is still available; 90
    means there is little left to do. An unknown score is treated as
    mid-range rather than as "nothing to fix", because not knowing is not
    evidence of quality.
    """
    if score is None:
        return 1.3
    return 1.0 + (100 - max(0, min(100, int(score)))) / 100.0


def resolve_rankmath(score: int | None) -> dict:
    """
    Turn a Rank Math score into the fields the pipeline carries for it.

    One helper for both paths — selection off the WordPress catalog, and the
    per-page fetch in Stage 2b that finds a score the catalog missed. Two
    resolutions is how a page ended up reported as `score=10/100 (unknown
    RankMath score)`.
    """
    normalized = None
    if score is not None:
        try:
            normalized = max(0, min(100, int(score)))
        except (TypeError, ValueError):
            normalized = None
    tier = wp_client.score_tier(normalized)
    return {
        "rankmath_score": normalized,
        "rankmath_tier": tier,
        "rankmath_tier_label": wp_client.tier_label(tier),
        "fixability_multiplier": fixability_multiplier(normalized),
    }


_RANKMATH_REASON_PREFIX = "RankMath "
_FALLBACK_REASON = "Low traffic opportunity"


def _rankmath_reason(resolved: dict) -> str | None:
    if resolved.get("rankmath_score") is None:
        return None
    return (
        f"{_RANKMATH_REASON_PREFIX}{resolved['rankmath_score']}/100 — "
        f"{resolved['rankmath_tier_label']}"
    )


def _with_rankmath_reason(reasons: list[str] | None, resolved: dict) -> list[str]:
    """Replace the Rank Math line in `reasons` so it matches `resolved`."""
    new_line = _rankmath_reason(resolved)
    out: list[str] = []
    placed = False
    for reason in reasons or []:
        if reason.startswith(_RANKMATH_REASON_PREFIX):
            if new_line and not placed:
                out.append(new_line)
                placed = True
            continue
        if reason == _FALLBACK_REASON and new_line:
            continue
        out.append(reason)
    if new_line and not placed:
        out.append(new_line)
    return out or [_FALLBACK_REASON]


def sync_rankmath_from_post(metrics: dict, post: dict | None) -> dict:
    """
    Reconcile a selected page's Rank Math fields with the score on its post.

    Selection reads the WordPress catalog, which can miss a page; the
    per-page fetch in Stage 2b then reads the score off the page itself. The
    post wins on disagreement — it is the page, the catalog is a listing of
    it — and an absent post score changes nothing.

    Priority is recomputed from the multipliers already on `metrics` so the
    number stays consistent with the fixability it now claims. Selection is
    NOT re-ordered: the page list for this run was already chosen, and
    re-ranking mid-run would mean the report disagrees with the run that
    produced it.

    Mutates and returns `metrics`.
    """
    post_score = ((post or {}).get("rankmath") or {}).get("seo_score")
    if post_score is None:
        return metrics
    try:
        post_score = int(post_score)
    except (TypeError, ValueError):
        return metrics

    resolved = resolve_rankmath(post_score)
    if metrics.get("rankmath_score") == resolved["rankmath_score"] and metrics.get(
        "rankmath_tier_label"
    ) == resolved["rankmath_tier_label"]:
        return metrics

    metrics.update(resolved)
    if "reasons" in metrics:
        metrics["reasons"] = _with_rankmath_reason(metrics["reasons"], resolved)
    if "missed_clicks" in metrics:
        metrics["priority"] = (
            float(metrics.get("missed_clicks") or 0.0)
            * float(metrics.get("neglect_multiplier") or 1.0)
            * resolved["fixability_multiplier"]
            * float(metrics.get("decay_multiplier") or 1.0)
        )
    return metrics


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


def clicks_window_label() -> str:
    """
    Unit for a missed-clicks figure.

    `missed_clicks` is sized from impressions over DATE_RANGE_DAYS and is not
    annualised, so "clicks/yr" is only true for a 365-day window.
    """
    days = int(config.DATE_RANGE_DAYS)
    return "clicks/yr" if days == 365 else f"clicks/{days}d"


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
    fixability = fixability_multiplier(score)

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
    excluded_keys = {canonical_key(u) for u in excluded_urls or ()}
    state_by_key = _states_by_key(page_states or {})
    site =(config.GSC_SITE_URL or "").rstrip("/")
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
        key = canonical_key(page)
        if key in excluded_keys or page.rstrip("/") == site:
            continue
        if _is_utility_page(page):
            skipped_utility.append(page)
            continue
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
        state = state_by_key.get(key) or {}
        modified = _wp_modified(post)

        # Edited since we last suggested it: capacity arrived and it got
        # attention. Hold it for a re-rank period rather than re-judging a
        # fix Google has not reprocessed yet.
        if state and _modified_changed(state.get("last_modified_seen"), modified):
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

        resolved = resolve_rankmath(score)
        reasons: list[str] = []
        clicks_unit = clicks_window_label()
        if scoring["missed_ctr_gap"] >= 1:
            reasons.append(
                f"~{scoring['missed_ctr_gap']:.0f} {clicks_unit} lost to weak CTR "
                f"for its position ({row['position']:.1f})"
            )
        if scoring["missed_position_gap"] >= 1:
            reasons.append(
                f"~{scoring['missed_position_gap']:.0f} {clicks_unit} available by "
                f"ranking better than {row['position']:.1f}"
            )
        if days_stale is not None and days_stale > 180:
            reasons.append(f"Not edited in {days_stale/365:.1f} years")
        if scoring["decay_multiplier"] > 1.0:
            reasons.append("Impressions falling vs the prior window")
        rankmath_line = _rankmath_reason(resolved)
        if rankmath_line:
            reasons.append(rankmath_line)
        if row.get("_from_wp_only"):
            reasons.append("No Search Console traffic yet")
        if not reasons:
            reasons.append(_FALLBACK_REASON)

        candidates.append({
            **row,
            **scoring,
            **resolved,
            "reasons": reasons,
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
