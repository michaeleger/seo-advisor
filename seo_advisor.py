"""Claude-powered SEO analysis for a single post."""
import json
import anthropic
import config

_client: anthropic.Anthropic | None = None

_SYSTEM = """\
You are a senior SEO consultant specializing in health and wellness content. \
Your job is to analyze underperforming blog posts and provide specific, actionable \
recommendations to improve their organic search performance.

You will be given:
- The post title, URL, and full text
- Google Search Console data: clicks, impressions, CTR, average position
- The top search queries already sending (some) traffic to this page
- RankMath SEO data: the author's chosen focus keyword, current meta title, meta description, and SEO score (if available)

Your response MUST be valid JSON matching this exact structure — no markdown, no extra text:
{
  "summary": "2-3 sentence diagnosis of why this post is underperforming and the biggest opportunity",
  "is_evergreen": true,
  "evergreen_rationale": "one sentence explaining why this topic is or isn't evergreen",
  "target_keywords": [
    {"keyword": "...", "rationale": "why this keyword fits and has opportunity", "intent": "informational|navigational|transactional|commercial"}
  ],
  "meta_description": "A compelling 150-160 character meta description that includes the primary keyword",
  "title_suggestions": [
    {"title": "...", "rationale": "why this title would improve CTR or rankings"}
  ],
  "phrases_to_add": [
    {"phrase": "...", "placement": "intro|h2_heading|body_paragraph|conclusion|meta_description"}
  ],
  "content_recommendations": [
    {"type": "rewrite_intro|add_section|improve_heading|add_faq|internal_link|meta_description",
     "suggestion": "specific actionable instruction"}
  ]
}

Provide 4-6 target keywords, 3 title suggestions, 4-6 phrases to add, and 3-5 content recommendations. \
Be specific — name the actual phrases, headings, and sections. Never give generic advice."""


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        api_key = config.ANTHROPIC_API_KEY
        if not api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set. Add it to your .env file "
                "or export it as an environment variable."
            )
        _client = anthropic.Anthropic(api_key=api_key)
    return _client


def analyze_post(metrics: dict, queries: list[dict], post: dict) -> dict | None:
    """
    Run Claude SEO analysis on one post.
    Returns parsed JSON dict or None on error.
    """
    top_queries = "\n".join(
        f"  • \"{q['query']}\" — {q['impressions']} impressions, "
        f"pos {q['position']:.1f}, CTR {q['ctr']*100:.1f}%"
        for q in queries[:15]
    ) or "  (no query data available)"

    rm = post.get("rankmath", {})
    rm_section = ""
    if any(rm.values()):
        score = f"{rm['seo_score']}/100" if rm.get("seo_score") is not None else "unknown"
        rm_section = f"""
RANKMATH SEO DATA (current state):
  Focus Keyword: {rm.get('focus_keyword') or 'not set'}
  SEO Score: {score}
  Meta Title: {rm.get('meta_title') or '(none — using post title)'}
  Meta Description: {rm.get('meta_description') or '(none)'}
"""

    prompt = f"""Analyze this underperforming blog post:

TITLE: {post['title']}
URL: {post['url']}

SEARCH CONSOLE METRICS (last {config.DATE_RANGE_DAYS} days):
  Clicks: {int(metrics['clicks'])}
  Impressions: {int(metrics['impressions'])}
  CTR: {metrics['ctr']*100:.2f}%
  Avg Position: {metrics['position']:.1f}

TOP SEARCH QUERIES DRIVING IMPRESSIONS:
{top_queries}
{rm_section}
POST CONTENT:
{post['content_plain']}"""

    try:
        response = _get_client().messages.create(
            model="claude-sonnet-4-6",
            max_tokens=4096,
            system=[
                {
                    "type": "text",
                    "text": _SYSTEM,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text.strip()
        # Strip markdown code fences if Claude wraps the JSON
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        return json.loads(raw.strip())
    except json.JSONDecodeError as exc:
        print(f"[seo_advisor] JSON parse error for {post['url']}: {exc}")
        return None
    except RuntimeError as exc:
        print(f"[seo_advisor] Configuration error: {exc}")
        raise
    except Exception as exc:
        print(f"[seo_advisor] Error analyzing {post['url']}: {exc}")
        return None
