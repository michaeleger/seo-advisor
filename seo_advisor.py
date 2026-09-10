"""
Stage 2 — local LLM keyword recommendations for a single underperforming post.

Uses Ollama (or OpenAI-compatible local server). Output is structured JSON that
is later handed to Claude for the polished final report.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

import requests

import config

log = logging.getLogger(__name__)

_SYSTEM = """\
You are an SEO keyword analyst for a health and wellness blog.
Given Search Console metrics, top queries, and post content, recommend keywords
to improve organic performance.

Respond with ONLY valid JSON (no markdown, no commentary). Use double quotes.
Do not put unescaped double quotes inside string values.

JSON shape:
{
  "primary_keyword": "best single focus keyword for this page",
  "target_keywords": [
    {
      "keyword": "...",
      "rationale": "why this keyword fits the post and has opportunity",
      "intent": "informational|navigational|transactional|commercial",
      "priority": "high|medium|low"
    }
  ],
  "query_gaps": [
    "search queries or themes the post should cover but currently under-serves"
  ],
  "notes": "1-2 sentences on why this page underperforms for search"
}

Provide 5-8 target_keywords. Prefer specific, searchable phrases over brand fluff.
Ground recommendations in the provided GSC queries and metrics when possible."""

_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "primary_keyword": {"type": "string"},
        "target_keywords": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "keyword": {"type": "string"},
                    "rationale": {"type": "string"},
                    "intent": {"type": "string"},
                    "priority": {"type": "string"},
                },
                "required": ["keyword", "rationale", "intent"],
            },
        },
        "query_gaps": {"type": "array", "items": {"type": "string"}},
        "notes": {"type": "string"},
    },
    "required": ["primary_keyword", "target_keywords", "notes"],
}


def _build_user_prompt(metrics: dict, queries: list[dict], post: dict) -> str:
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
RANKMATH:
  Focus Keyword: {rm.get('focus_keyword') or 'not set'}
  SEO Score: {score}
  Meta Title: {rm.get('meta_title') or '(none)'}
  Meta Description: {rm.get('meta_description') or '(none)'}
"""

    content = post.get("content_plain") or ""
    max_chars = 2200
    if len(content) > max_chars:
        content = content[:max_chars] + "\n\n[… truncated …]"

    reasons = metrics.get("reasons") or []
    reasons_line = "; ".join(reasons) if reasons else "flagged as low performer"

    return f"""Recommend keywords for this underperforming post.

TITLE: {post['title']}
URL: {post['url']}
FLAG REASONS: {reasons_line}

GSC METRICS (last {config.DATE_RANGE_DAYS} days):
  Clicks: {int(metrics['clicks'])}
  Impressions: {int(metrics['impressions'])}
  CTR: {metrics['ctr']*100:.2f}%
  Avg Position: {metrics['position']:.1f}

TOP GSC QUERIES:
{top_queries}
{rm_section}
POST CONTENT:
{content}"""


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        parts = text.split("```")
        if len(parts) >= 2:
            text = parts[1]
            if text.lstrip().startswith("json"):
                text = text.lstrip()[4:]
            text = text.strip()
    return text


def _repair_json_text(text: str) -> str:
    text = _strip_fences(text)
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        text = text[start : end + 1]
    text = re.sub(r",\s*([}\]])", r"\1", text)
    text = (
        text.replace("\u201c", '"')
        .replace("\u201d", '"')
        .replace("\u2018", "'")
        .replace("\u2019", "'")
    )
    return text


def _extract_json(raw: str) -> dict:
    text = (raw or "").strip()
    if not text:
        raise json.JSONDecodeError("empty model response", text, 0)

    last_err: Exception | None = None
    for cand in (text, _repair_json_text(text)):
        try:
            return json.loads(cand)
        except json.JSONDecodeError as exc:
            last_err = exc
            start, end = cand.find("{"), cand.rfind("}")
            if start >= 0 and end > start:
                try:
                    return json.loads(cand[start : end + 1])
                except json.JSONDecodeError as exc2:
                    last_err = exc2
    assert last_err is not None
    raise last_err


def _normalize_analysis(data: dict) -> dict:
    """Normalize local LLM output into a stable shape for Claude + template report."""
    keywords = data.get("target_keywords") or []
    clean_kw = []
    for k in keywords:
        if not isinstance(k, dict) or not k.get("keyword"):
            continue
        clean_kw.append({
            "keyword": str(k["keyword"]).strip(),
            "rationale": str(k.get("rationale") or "").strip(),
            "intent": str(k.get("intent") or "informational").strip().lower(),
            "priority": str(k.get("priority") or "medium").strip().lower(),
        })

    primary = str(data.get("primary_keyword") or (clean_kw[0]["keyword"] if clean_kw else "")).strip()
    notes = str(data.get("notes") or "").strip()
    gaps = [str(g).strip() for g in (data.get("query_gaps") or []) if str(g).strip()]

    # Fields expected by existing report.py template (compat layer)
    return {
        "primary_keyword": primary,
        "target_keywords": clean_kw,
        "query_gaps": gaps,
        "notes": notes,
        "summary": notes or f"Primary keyword opportunity: {primary}",
        "is_evergreen": data.get("is_evergreen"),
        "evergreen_rationale": data.get("evergreen_rationale") or "",
        "meta_description": data.get("meta_description") or "",
        "title_suggestions": data.get("title_suggestions") or [],
        "phrases_to_add": data.get("phrases_to_add") or [],
        "content_recommendations": data.get("content_recommendations") or [],
    }


def _save_raw_failure(url: str, raw: str) -> None:
    try:
        out_dir = Path(config.REPORTS_DIR)
        out_dir.mkdir(parents=True, exist_ok=True)
        slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", url.rstrip("/").split("/")[-1])[:60] or "unknown"
        path = out_dir / f"llm_raw_fail_{slug}.txt"
        path.write_text(raw or "", encoding="utf-8")
        log.warning("Saved raw local-LLM output to %s", path)
    except Exception as exc:
        log.debug("Could not save raw LLM output: %s", exc)


def _call_ollama(system: str, user: str, *, use_schema: bool = True) -> str:
    url = f"{config.OLLAMA_BASE_URL}/api/chat"
    payload: dict[str, Any] = {
        "model": config.OLLAMA_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "stream": False,
        "format": _JSON_SCHEMA if use_schema else "json",
        "options": {
            "temperature": config.LLM_TEMPERATURE,
            "num_predict": config.LLM_MAX_TOKENS,
            "num_ctx": config.OLLAMA_NUM_CTX,
            "num_thread": config.OLLAMA_NUM_THREAD,
        },
    }
    log.debug("Ollama keyword pass model=%s", config.OLLAMA_MODEL)
    resp = requests.post(url, json=payload, timeout=config.LLM_TIMEOUT_SECONDS)
    resp.raise_for_status()
    data = resp.json()
    message = data.get("message") or {}
    content = message.get("content") or ""
    if not content.strip():
        thinking = message.get("thinking") or ""
        if thinking.strip():
            content = thinking
    if not content.strip():
        raise RuntimeError(
            f"Ollama returned empty content for model {config.OLLAMA_MODEL}."
        )
    return content


def _call_openai_compat(system: str, user: str) -> str:
    base = config.OPENAI_COMPAT_BASE_URL or f"{config.OLLAMA_BASE_URL}/v1"
    model = config.OPENAI_COMPAT_MODEL or config.OLLAMA_MODEL
    url = f"{base.rstrip('/')}/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {config.OPENAI_COMPAT_API_KEY}",
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": config.LLM_TEMPERATURE,
        "max_tokens": config.LLM_MAX_TOKENS,
        "response_format": {"type": "json_object"},
    }
    resp = requests.post(url, headers=headers, json=payload, timeout=config.LLM_TIMEOUT_SECONDS)
    resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"]


def _complete_local(system: str, user: str) -> str:
    provider = config.LOCAL_LLM_PROVIDER
    if provider in ("ollama", "local"):
        return _call_ollama(system, user)
    if provider in ("openai_compat", "openai", "llamacpp", "llama.cpp"):
        return _call_openai_compat(system, user)
    raise RuntimeError(
        f"Unknown LOCAL_LLM_PROVIDER={provider!r}. Use ollama or openai_compat."
    )


def recommend_keywords(metrics: dict, queries: list[dict], post: dict) -> dict | None:
    """
    Local-LLM stage: keyword recommendations for one post.
    Returns normalized dict or None on failure.
    """
    prompt = _build_user_prompt(metrics, queries, post)
    url = post.get("url", "")

    try:
        raw = _complete_local(_SYSTEM, prompt)
        try:
            data = _extract_json(raw)
        except json.JSONDecodeError as first_err:
            log.warning("JSON parse error for %s: %s — repair pass", url, first_err)
            _save_raw_failure(url, raw)
            if config.LOCAL_LLM_PROVIDER in ("ollama", "local"):
                repair_user = (
                    "Fix this into valid JSON only (primary_keyword, target_keywords, "
                    "query_gaps, notes). No markdown.\n\n"
                    f"{raw[:5000]}"
                )
                raw = _call_ollama(
                    "You fix invalid JSON. Output only valid JSON.",
                    repair_user,
                    use_schema=True,
                )
                data = _extract_json(raw)
            else:
                raise
        return _normalize_analysis(data)
    except json.JSONDecodeError as exc:
        log.warning("JSON parse error for %s after repair: %s", url, exc)
        return None
    except RuntimeError:
        raise
    except requests.RequestException as exc:
        log.error("Local LLM request failed for %s: %s", url, exc)
        return None
    except Exception as exc:
        log.error("Error analyzing %s: %s", url, exc)
        return None


# Back-compat name used by older call sites
def analyze_post(metrics: dict, queries: list[dict], post: dict) -> dict | None:
    return recommend_keywords(metrics, queries, post)
