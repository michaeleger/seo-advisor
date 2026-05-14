"""Fetch post content from WordPress REST API by URL slug."""
import re
import requests
import config


def _strip_html(html: str) -> str:
    text = re.sub(r"<[^>]+>", " ", html)
    return re.sub(r"\s+", " ", text).strip()


def get_post_content(page_url: str) -> dict | None:
    """
    Given a full page URL, fetch the matching WordPress post's title and content.
    Returns None if the post cannot be found.
    """
    # Derive the slug from the URL
    slug = page_url.rstrip("/").split("/")[-1]
    if not slug:
        return None

    try:
        resp = requests.get(
            f"{config.WP_SITE_URL}/wp-json/wp/v2/posts",
            params={"slug": slug, "_fields": "id,title,content,link,meta", "per_page": 1},
            timeout=15,
        )
        resp.raise_for_status()
        posts = resp.json()
        if not posts:
            return None
        p = posts[0]
        meta = p.get("meta", {})
        rankmath = {
            "focus_keyword": meta.get("rank_math_focus_keyword", ""),
            "seo_score": meta.get("rank_math_seo_score") or None,
            "meta_title": meta.get("rank_math_title", ""),
            "meta_description": meta.get("rank_math_description", ""),
        }
        return {
            "id": p["id"],
            "title": p["title"]["rendered"],
            "url": p["link"],
            "content_plain": _strip_html(p["content"]["rendered"])[:3000],
            "rankmath": rankmath,
        }
    except Exception as exc:
        print(f"[wp_client] Could not fetch post for {page_url}: {exc}")
        return None
