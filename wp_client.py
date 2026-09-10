"""Fetch post content and Rank Math data from WordPress REST API."""
from __future__ import annotations

import html as html_lib
import logging
import re
from typing import Any
from urllib.parse import urlparse

import requests

import config

log = logging.getLogger(__name__)


def _strip_html(html: str) -> str:
    text = re.sub(r"<[^>]+>", " ", html)
    text = html_lib.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


# ── Content structure (mirrors what Rank Math actually scores) ───────────────
# Regex rather than a parser: WordPress `content.rendered` is well-formed
# enough for these signals, and it keeps the dependency list at zero.
_HEADING_RE = re.compile(r"<h([1-6])\b[^>]*>(.*?)</h\1\s*>", re.I | re.S)
_PARA_RE = re.compile(r"<p\b[^>]*>(.*?)</p\s*>", re.I | re.S)
_IMG_RE = re.compile(r"<img\b[^>]*>", re.I)
_ANCHOR_RE = re.compile(r"<a\b([^>]*)>", re.I)
_ALT_RE = re.compile(r"\balt\s*=\s*[\"']([^\"']*)[\"']", re.I)
_HREF_RE = re.compile(r"\bhref\s*=\s*[\"']([^\"']+)[\"']", re.I)
_REL_RE = re.compile(r"\brel\s*=\s*[\"']([^\"']*)[\"']", re.I)

# Rank Math flags paragraphs longer than this in its readability checks.
_LONG_PARAGRAPH_WORDS = 120


def _bare_host(url: str) -> str:
    host = (urlparse(url or "").netloc or "").lower()
    return host[4:] if host.startswith("www.") else host


def _headings(content_html: str) -> list[dict]:
    out: list[dict] = []
    for level, inner in _HEADING_RE.findall(content_html or ""):
        text = _strip_html(inner)
        if text:
            out.append({"level": int(level), "text": text[:160]})
    return out


def _link_counts(content_html: str, site_host: str) -> dict[str, int]:
    internal = external = external_dofollow = 0
    for attrs in _ANCHOR_RE.findall(content_html or ""):
        href_m = _HREF_RE.search(attrs)
        if not href_m:
            continue
        href = href_m.group(1).strip()
        if href.startswith("#") or href.lower().startswith(
            ("mailto:", "tel:", "javascript:", "data:")
        ):
            continue
        host = _bare_host(href)
        if not host or host == site_host:
            internal += 1
            continue
        external += 1
        rel_m = _REL_RE.search(attrs)
        if not rel_m or "nofollow" not in rel_m.group(1).lower():
            external_dofollow += 1
    return {
        "internal_links": internal,
        "external_links": external,
        "external_dofollow_links": external_dofollow,
    }


def content_structure(content_html: str, *, site_url: str | None = None) -> dict:
    """
    Summarize a post body the way Rank Math scores it.

    Measurements only — deliberately no article text. The published page is
    the source of truth for content, markup, images and styling; a stripped
    copy here would be a degraded duplicate of something already at a URL.
    """
    src = content_html or ""
    plain = _strip_html(src)
    total_words = len(plain.split())

    paragraphs = [p for p in (_strip_html(x) for x in _PARA_RE.findall(src)) if p]
    long_paragraphs = sum(
        1 for p in paragraphs if len(p.split()) > _LONG_PARAGRAPH_WORDS
    )

    images = _IMG_RE.findall(src)
    missing_alt = 0
    for tag in images:
        alt_m = _ALT_RE.search(tag)
        if not alt_m or not alt_m.group(1).strip():
            missing_alt += 1

    site_host = _bare_host(site_url or getattr(config, "WP_SITE_URL", "") or "")

    return {
        "word_count": total_words,
        "headings": _headings(src),
        "paragraph_count": len(paragraphs),
        "long_paragraphs": long_paragraphs,
        "image_count": len(images),
        "images_missing_alt": missing_alt,
        **_link_counts(src, site_host),
    }


def _slug_from_url(page_url: str) -> str | None:
    path = urlparse(page_url).path.rstrip("/")
    if not path:
        return None
    slug = path.split("/")[-1]
    return slug or None


def _auth() -> tuple | None:
    user = getattr(config, "WP_APP_USER", "") or ""
    password = getattr(config, "WP_APP_PASSWORD", "") or ""
    if user and password:
        return (user, password)
    return None


def _session_get(url: str, params: dict | None = None, timeout: int = 25) -> requests.Response:
    return requests.get(
        url,
        params=params or {},
        timeout=timeout,
        allow_redirects=True,
        auth=_auth(),
    )


def _normalize_score(raw: Any) -> int | None:
    if raw is None or raw == "":
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _rankmath_from_item(p: dict) -> dict:
    """Prefer dedicated rankmath REST field (plugin), else post meta."""
    if isinstance(p.get("rankmath"), dict) and p["rankmath"]:
        rm = p["rankmath"]
        return {
            "focus_keyword": (rm.get("focus_keyword") or "") or "",
            "seo_score": _normalize_score(rm.get("seo_score")),
            "meta_title": (rm.get("meta_title") or "") or "",
            "meta_description": (rm.get("meta_description") or "") or "",
        }
    meta = p.get("meta") or {}
    return {
        "focus_keyword": meta.get("rank_math_focus_keyword", "") or "",
        "seo_score": _normalize_score(
            meta.get("rank_math_seo_score")
            if meta.get("rank_math_seo_score") not in (None, "")
            else meta.get("rankmath_seo_score")
        ),
        "meta_title": meta.get("rank_math_title", "") or "",
        "meta_description": meta.get("rank_math_description", "") or "",
    }


def _to_post_dict(p: dict) -> dict:
    content_html = (p.get("content") or {}).get("rendered") or ""
    title = (p.get("title") or {}).get("rendered") or ""
    title = html_lib.unescape(re.sub(r"<[^>]+>", "", title)).strip()
    rankmath = _rankmath_from_item(p)
    return {
        "id": p.get("id"),
        "title": title,
        "url": p.get("link") or "",
        "content_plain": _strip_html(content_html)[:3000],
        "content": content_structure(content_html),
        "rankmath": rankmath,
        "type": p.get("type") or "post",
        "slug": p.get("slug") or _slug_from_url(p.get("link") or "") or "",
    }


def _fetch_by_slug(endpoint: str, slug: str) -> dict | None:
    base = config.WP_SITE_URL.rstrip("/")
    resp = _session_get(
        f"{base}/wp-json/wp/v2/{endpoint}",
        params={
            "slug": slug,
            "_fields": "id,title,content,link,meta,type,slug,rankmath",
            "per_page": 1,
        },
    )
    resp.raise_for_status()
    items = resp.json()
    if not items:
        return None
    return items[0]


def get_post_content(page_url: str) -> dict | None:
    """Fetch one WordPress post/page by URL (includes Rank Math when exposed)."""
    slug = _slug_from_url(page_url)
    if not slug:
        return None

    try:
        for endpoint in ("posts", "pages"):
            item = _fetch_by_slug(endpoint, slug)
            if item:
                return _to_post_dict(item)

        base = config.WP_SITE_URL.rstrip("/")
        q = slug[:40].replace("-", " ")
        for endpoint in ("posts", "pages"):
            resp = _session_get(
                f"{base}/wp-json/wp/v2/{endpoint}",
                params={
                    "search": q,
                    "_fields": "id,title,content,link,meta,type,slug,rankmath",
                    "per_page": 10,
                },
            )
            resp.raise_for_status()
            for item in resp.json():
                item_slug = (item.get("slug") or "").lower()
                if not item_slug:
                    continue
                if (
                    item_slug == slug
                    or item_slug.endswith(slug)
                    or slug.endswith(item_slug)
                    or slug in item_slug
                    or item_slug in slug
                ):
                    return _to_post_dict(item)
                link_slug = _slug_from_url(item.get("link") or "")
                if link_slug and (
                    link_slug == slug or slug in link_slug or link_slug in slug
                ):
                    return _to_post_dict(item)
        return None
    except Exception as exc:
        log.warning("Could not fetch post for %s: %s", page_url, exc)
        return None


def fetch_rankmath_scores_via_etbh_endpoint(max_items: int = 500) -> dict[int, dict]:
    """
    Preferred free path: our mu-plugin endpoint that reads RankMath meta RankMath
    already computed (not Claude ~$1 audits).

      GET /wp-json/etbh-seo/v1/rankmath-scores

    Install: wordpress-plugin/eager-rankmath-rest.php → wp-content/mu-plugins/
    """
    base = config.WP_SITE_URL.rstrip("/")
    by_id: dict[int, dict] = {}
    page = 1
    while len(by_id) < max_items:
        per_page = min(100, max_items - len(by_id))
        resp = _session_get(
            f"{base}/wp-json/etbh-seo/v1/rankmath-scores",
            params={"page": page, "per_page": per_page, "post_type": "post,page"},
            timeout=40,
        )
        if resp.status_code == 404:
            log.info(
                "etbh-seo rankmath-scores endpoint not installed yet "
                "(copy wordpress-plugin/eager-rankmath-rest.php to mu-plugins)."
            )
            return {}
        if resp.status_code >= 400:
            log.warning(
                "etbh-seo/rankmath-scores HTTP %s: %s",
                resp.status_code,
                resp.text[:200],
            )
            return {}
        data = resp.json() if resp.content else {}
        rows = data.get("items") if isinstance(data, dict) else data
        if not rows:
            break
        for row in rows:
            if not isinstance(row, dict):
                continue
            pid = row.get("id")
            if pid is None:
                continue
            pid = int(pid)
            rm = row.get("rankmath") if isinstance(row.get("rankmath"), dict) else {}
            score = _normalize_score(
                row.get("seo_score") if row.get("seo_score") is not None else rm.get("seo_score")
            )
            by_id[pid] = {
                "id": pid,
                "seo_score": score,
                "title": row.get("title") or "",
                "url": row.get("url") or "",
                "focus_keyword": row.get("focus_keyword")
                or rm.get("focus_keyword")
                or "",
                "score_source": "rank_math_seo_score",
            }
        total_pages = int((data.get("total_pages") if isinstance(data, dict) else 1) or 1)
        if page >= total_pages or len(rows) < per_page:
            break
        page += 1
        if page > 50:
            break

    log.info(
        "RankMath via etbh-seo endpoint: %d posts, %d with scores (free plugin meta).",
        len(by_id),
        sum(1 for v in by_id.values() if v.get("seo_score") is not None),
    )
    return by_id


def fetch_rankmath_scores_via_links_api(max_items: int = 500) -> dict[int, dict]:
    """
    Fallback: Rank Math's own links analyzer API (often admin-only).

    GET /wp-json/rankmath/v1/links/posts
    Editors frequently get 403 — use etbh-seo plugin endpoint instead.
    """
    if not _auth():
        return {}

    base = config.WP_SITE_URL.rstrip("/")
    by_id: dict[int, dict] = {}
    ranges = ("bad", "good", "great", "no-score", "")
    for score_range in ranges:
        page = 1
        while len(by_id) < max_items:
            params: dict[str, Any] = {
                "page": page,
                "per_page": 100,
                "orderby": "seo_score",
                "order": "ASC",
            }
            if score_range:
                params["seo_score_range"] = score_range
            resp = _session_get(
                f"{base}/wp-json/rankmath/v1/links/posts",
                params=params,
                timeout=40,
            )
            if resp.status_code in (401, 403):
                log.info(
                    "RankMath /links/posts HTTP %s (need admin or etbh-seo plugin).",
                    resp.status_code,
                )
                return by_id
            if resp.status_code >= 400:
                log.warning(
                    "RankMath /links/posts HTTP %s: %s",
                    resp.status_code,
                    resp.text[:200],
                )
                break
            data = resp.json()
            if isinstance(data, dict):
                rows = (
                    data.get("posts")
                    or data.get("items")
                    or data.get("data")
                    or []
                )
            else:
                rows = data if isinstance(data, list) else []
            if not rows:
                break
            for row in rows:
                if not isinstance(row, dict):
                    continue
                pid = row.get("id") or row.get("post_id") or row.get("ID")
                if pid is None:
                    continue
                pid = int(pid)
                score = _normalize_score(
                    row.get("seo_score")
                    or row.get("score")
                    or row.get("rank_math_seo_score")
                )
                title = row.get("title") or row.get("post_title") or ""
                if isinstance(title, dict):
                    title = title.get("rendered") or ""
                url = row.get("url") or row.get("permalink") or row.get("link") or ""
                by_id[pid] = {
                    "id": pid,
                    "seo_score": score,
                    "title": html_lib.unescape(re.sub(r"<[^>]+>", "", str(title))).strip(),
                    "url": url,
                    "focus_keyword": row.get("focus_keyword")
                    or row.get("rank_math_focus_keyword")
                    or "",
                    "score_source": "rankmath_links_api",
                }
            if len(rows) < 100:
                break
            page += 1
            if page > 50:
                break
        if len(by_id) >= max_items:
            break

    if by_id:
        log.info(
            "RankMath links API: %d posts with scores.",
            sum(1 for v in by_id.values() if v.get("seo_score") is not None),
        )
    return by_id


def fetch_rankmath_scores(max_items: int = 500) -> dict[int, dict]:
    """Real RankMath plugin scores — never LLM audit scores."""
    by_id = fetch_rankmath_scores_via_etbh_endpoint(max_items=max_items)
    if by_id:
        return by_id
    by_id = fetch_rankmath_scores_via_links_api(max_items=max_items)
    if by_id:
        return by_id
    log.warning(
        "No RankMath scores available. Install "
        "wordpress-plugin/eager-rankmath-rest.php as mu-plugin so we use "
        "RankMath's free stored scores instead of a ~$1 Claude audit."
    )
    return {}


def list_content_with_rankmath(
    max_items: int = 200,
    *,
    types: tuple[str, ...] = ("posts", "pages"),
) -> list[dict]:
    """
    List published posts/pages with Rank Math fields.

    Score sources (in order):
      1) Authenticated RankMath /links/posts  → real plugin score
      2) REST rankmath field / post meta       → needs mu-plugin or public meta
    """
    base = config.WP_SITE_URL.rstrip("/")
    score_by_id = fetch_rankmath_scores(max_items=max(max_items, 500))

    out: list[dict] = []
    for endpoint in types:
        page = 1
        while len(out) < max_items:
            per_page = min(100, max_items - len(out))
            resp = _session_get(
                f"{base}/wp-json/wp/v2/{endpoint}",
                params={
                    "per_page": per_page,
                    "page": page,
                    "status": "publish",
                    "_fields": "id,title,content,link,meta,type,slug,rankmath",
                    "orderby": "modified",
                    "order": "desc",
                },
                timeout=40,
            )
            if resp.status_code == 400 and page > 1:
                break
            resp.raise_for_status()
            batch = resp.json()
            if not batch:
                break
            for item in batch:
                post = _to_post_dict(item)
                pid = post.get("id")
                if pid is not None and int(pid) in score_by_id:
                    sc = score_by_id[int(pid)]
                    rm = dict(post.get("rankmath") or {})
                    if sc.get("seo_score") is not None:
                        rm["seo_score"] = sc["seo_score"]
                    if sc.get("focus_keyword"):
                        rm["focus_keyword"] = sc["focus_keyword"]
                    rm["score_source"] = "rankmath_links_api"
                    post["rankmath"] = rm
                elif (post.get("rankmath") or {}).get("seo_score") is not None:
                    post["rankmath"]["score_source"] = "wp_rest_meta"
                out.append(post)
            total_pages = int(resp.headers.get("X-WP-TotalPages") or 1)
            if page >= total_pages:
                break
            page += 1

    # Include any scored posts from RankMath API missing from the WP list slice
    seen_ids = {p.get("id") for p in out}
    for pid, sc in score_by_id.items():
        if pid in seen_ids or len(out) >= max_items:
            continue
        if not sc.get("url") and not sc.get("title"):
            continue
        out.append(
            {
                "id": pid,
                "title": sc.get("title") or f"Post {pid}",
                "url": sc.get("url") or "",
                "content_plain": "",
                "content": content_structure(""),
                "rankmath": {
                    "seo_score": sc.get("seo_score"),
                    "focus_keyword": sc.get("focus_keyword") or "",
                    "meta_title": "",
                    "meta_description": "",
                    "score_source": "rankmath_links_api",
                },
                "type": "post",
                "slug": _slug_from_url(sc.get("url") or "") or "",
            }
        )
    return out[:max_items]


def rankmath_score_available(posts: list[dict]) -> bool:
    return any(
        (p.get("rankmath") or {}).get("seo_score") is not None for p in posts
    )


def score_tier(seo_score: int | None) -> int:
    """
    Lower tier number = more improvable = higher priority.
      0: <20, 1: <40, 2: <60, 3: <80, 4: >=80, 5: unknown
    """
    if seo_score is None:
        return 5
    if seo_score < 20:
        return 0
    if seo_score < 40:
        return 1
    if seo_score < 60:
        return 2
    if seo_score < 80:
        return 3
    return 4


def tier_label(tier: int) -> str:
    return {
        0: "under 20 (critical)",
        1: "20–39 (poor)",
        2: "40–59 (fair)",
        3: "60–79 (good — still improvable)",
        4: "80+ (strong)",
        5: "unknown RankMath score",
    }.get(tier, "unknown")
