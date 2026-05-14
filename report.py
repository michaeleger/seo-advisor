"""Generate a self-contained HTML SEO report."""
from datetime import date
from typing import Any


# ── helpers ──────────────────────────────────────────────────────────────────

def _pct(v: float) -> str:
    return f"{v * 100:.1f}%"


def _pos(v: float) -> str:
    return f"{v:.1f}"


def _badge(text: str, color: str) -> str:
    return f'<span class="badge" style="background:{color}">{text}</span>'


def _metric_pill(label: str, value: str, warn: bool = False, delta: str = "") -> str:
    color = "#e74c3c" if warn else "#2ecc71"
    return (
        f'<div class="pill">'
        f'<span class="pill-label">{label}</span>'
        f'<span class="pill-value" style="color:{color}">{value}{delta}</span>'
        f"</div>"
    )


def _reason_tags(reasons: list[str]) -> str:
    return " ".join(_badge(r, "#e74c3c") for r in reasons)


def _delta_span(new_val: float, old_val: float | None, fmt: str = "+.0f", invert: bool = False) -> str:
    """Render a delta badge. invert=True when lower is better (e.g. position)."""
    if old_val is None:
        return ""
    diff = new_val - old_val
    if diff == 0:
        return '<span style="color:#888;font-size:.8em"> (=)</span>'
    good = (diff < 0) if invert else (diff > 0)
    color = "#2ecc71" if good else "#e74c3c"
    sign = "+" if diff > 0 else ""
    return f'<span style="color:{color};font-size:.8em;margin-left:.3em">({sign}{diff:{fmt.lstrip("+")}})</span>'


def _keyword_rows(keywords: list[dict]) -> str:
    rows = "".join(
        f"<tr><td><code>{k['keyword']}</code></td><td>{k['rationale']}</td></tr>"
        for k in keywords
    )
    return f"<table><thead><tr><th>Keyword</th><th>Rationale</th></tr></thead><tbody>{rows}</tbody></table>"


def _title_list(titles: list[dict]) -> str:
    items = "".join(
        f"<li><strong>{t['title']}</strong><br><small>{t['rationale']}</small></li>"
        for t in titles
    )
    return f"<ol>{items}</ol>"


def _phrase_rows(phrases: list[dict]) -> str:
    rows = "".join(
        f'<tr><td><em>&ldquo;{p["phrase"]}&rdquo;</em></td>'
        f'<td><span class="placement">{p["placement"]}</span></td></tr>'
        for p in phrases
    )
    return f"<table><thead><tr><th>Phrase</th><th>Placement</th></tr></thead><tbody>{rows}</tbody></table>"


def _rankmath_panel(rankmath: dict) -> str:
    if not rankmath or not any(rankmath.values()):
        return ""
    score = rankmath.get("seo_score")
    if score is not None:
        color = "#2ecc71" if score >= 80 else ("#f39c12" if score >= 50 else "#e74c3c")
        score_html = f'<span style="color:{color};font-weight:700">{score}/100</span>'
    else:
        score_html = '<span style="color:#999">—</span>'
    kw = rankmath.get("focus_keyword") or '<span style="color:#999">not set</span>'
    mt = rankmath.get("meta_title") or '<em style="color:#999">using post title</em>'
    md = rankmath.get("meta_description") or '<em style="color:#999">none</em>'
    return f"""
    <div class="rm-panel">
      <h4>RankMath SEO Snapshot</h4>
      <div class="rm-grid">
        <div class="rm-row"><span class="rm-label">Focus Keyword</span><span class="rm-val"><code>{kw}</code></span></div>
        <div class="rm-row"><span class="rm-label">SEO Score</span><span class="rm-val">{score_html}</span></div>
        <div class="rm-row"><span class="rm-label">Meta Title</span><span class="rm-val">{mt}</span></div>
        <div class="rm-row"><span class="rm-label">Meta Description</span><span class="rm-val">{md}</span></div>
      </div>
    </div>"""


def _reco_list(recos: list[dict]) -> str:
    type_colors = {
        "rewrite_intro": "#8e44ad",
        "add_section": "#2980b9",
        "improve_heading": "#16a085",
        "add_faq": "#d35400",
        "internal_link": "#27ae60",
        "meta_description": "#c0392b",
    }
    items = []
    for r in recos:
        color = type_colors.get(r["type"], "#555")
        tag = _badge(r["type"].replace("_", " "), color)
        items.append(f"<li>{tag} {r['suggestion']}</li>")
    return f"<ul>{''.join(items)}</ul>"


def _post_section(idx: int, metrics: dict, post: dict, analysis: dict,
                  prev_metrics: dict | None = None) -> str:
    ctr_warn = metrics["ctr"] < 0.05
    pos_warn = metrics["position"] > 20
    pm = prev_metrics

    pills = (
        _metric_pill("Clicks", str(int(metrics["clicks"])),
                     delta=_delta_span(metrics["clicks"], pm["clicks"] if pm else None, fmt="+.0f"))
        + _metric_pill("Impressions", str(int(metrics["impressions"])),
                       delta=_delta_span(metrics["impressions"], pm["impressions"] if pm else None, fmt="+.0f"))
        + _metric_pill("CTR", _pct(metrics["ctr"]), warn=ctr_warn,
                       delta=_delta_span(metrics["ctr"] * 100, pm["ctr"] * 100 if pm else None, fmt="+.1f"))
        + _metric_pill("Avg Position", _pos(metrics["position"]), warn=pos_warn,
                       delta=_delta_span(metrics["position"], pm["position"] if pm else None, fmt="+.1f", invert=True))
    )

    rm_panel = _rankmath_panel(post.get("rankmath", {}))

    if analysis:
        body = f"""
        {rm_panel}
        <div class="summary-box">{analysis['summary']}</div>
        <h4>Target Keywords</h4>
        {_keyword_rows(analysis.get('target_keywords', []))}
        <h4>Suggested Titles</h4>
        {_title_list(analysis.get('title_suggestions', []))}
        <h4>Phrases to Add</h4>
        {_phrase_rows(analysis.get('phrases_to_add', []))}
        <h4>Content Recommendations</h4>
        {_reco_list(analysis.get('content_recommendations', []))}
        """
    else:
        body = f'{rm_panel}<p class="error">Analysis unavailable for this post.</p>'

    reasons_html = _reason_tags(metrics.get("reasons", []))

    return f"""
    <details class="post-card" id="post-{idx}">
      <summary>
        <span class="post-num">#{idx}</span>
        <span class="post-title">
          <a href="{post['url']}" target="_blank">{post['title']}</a>
        </span>
        <span class="reasons">{reasons_html}</span>
      </summary>
      <div class="metrics-row">{pills}</div>
      {body}
    </details>
    """


def _overview_row(idx: int, metrics: dict, post: dict, prev_metrics: dict | None = None) -> str:
    pm = prev_metrics
    return (
        f"<tr>"
        f'<td><a href="#post-{idx}">#{idx}</a></td>'
        f'<td><a href="{post["url"]}" target="_blank">{post["title"]}</a></td>'
        f"<td>{int(metrics['impressions'])}"
        f"{_delta_span(metrics['impressions'], pm['impressions'] if pm else None, fmt='+.0f')}</td>"
        f"<td>{int(metrics['clicks'])}"
        f"{_delta_span(metrics['clicks'], pm['clicks'] if pm else None, fmt='+.0f')}</td>"
        f'<td class="{"warn" if metrics["ctr"] < 0.05 else ""}">{_pct(metrics["ctr"])}'
        f"{_delta_span(metrics['ctr']*100, pm['ctr']*100 if pm else None, fmt='+.1f')}</td>"
        f'<td class="{"warn" if metrics["position"] > 20 else ""}">{_pos(metrics["position"])}'
        f"{_delta_span(metrics['position'], pm['position'] if pm else None, fmt='+.1f', invert=True)}</td>"
        f"</tr>"
    )


# ── public API ───────────────────────────────────────────────────────────────

def build_report(results: list[dict], output_path: str = "seo_report.html") -> str:
    """
    results: list of dicts with keys: metrics, post, analysis, prev_metrics (optional)
    Returns the path to the written file.
    """
    overview_rows = "".join(
        _overview_row(i + 1, r["metrics"], r["post"], r.get("prev_metrics"))
        for i, r in enumerate(results)
    )
    post_sections = "".join(
        _post_section(i + 1, r["metrics"], r["post"], r["analysis"], r.get("prev_metrics"))
        for i, r in enumerate(results)
    )

    analyzed = sum(1 for r in results if r["analysis"])
    site = results[0]["post"]["url"].split("/")[2] if results else "your site"

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>SEO Report — {site}</title>
<style>
  :root {{
    --bg: #f5f6fa; --card: #fff; --border: #e1e4e8;
    --text: #24292e; --muted: #586069; --accent: #0366d6;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
          background: var(--bg); color: var(--text); line-height: 1.6; }}
  header {{ background: #1a1a2e; color: #fff; padding: 2rem; }}
  header h1 {{ font-size: 1.6rem; margin-bottom: .4rem; }}
  header p {{ color: #aaa; font-size: .9rem; }}
  .stats {{ display: flex; gap: 1.5rem; margin-top: 1rem; }}
  .stat {{ background: rgba(255,255,255,.1); border-radius: 8px;
           padding: .6rem 1.2rem; text-align: center; }}
  .stat-val {{ font-size: 1.6rem; font-weight: 700; }}
  .stat-label {{ font-size: .75rem; color: #ccc; }}
  main {{ max-width: 960px; margin: 2rem auto; padding: 0 1rem; }}
  h2 {{ font-size: 1.2rem; margin: 2rem 0 1rem; border-bottom: 2px solid var(--border);
        padding-bottom: .5rem; }}
  h4 {{ margin: 1.2rem 0 .5rem; color: var(--muted); font-size: .85rem;
        text-transform: uppercase; letter-spacing: .05em; }}
  table {{ width: 100%; border-collapse: collapse; font-size: .9rem; margin-bottom: 1rem; }}
  th {{ background: var(--bg); text-align: left; padding: .5rem .75rem;
        font-size: .8rem; color: var(--muted); border-bottom: 2px solid var(--border); }}
  td {{ padding: .5rem .75rem; border-bottom: 1px solid var(--border); }}
  td.warn {{ color: #e74c3c; font-weight: 600; }}
  tr:hover td {{ background: #f9f9f9; }}
  .post-card {{ background: var(--card); border: 1px solid var(--border);
                border-radius: 8px; margin-bottom: 1rem;
                box-shadow: 0 1px 3px rgba(0,0,0,.06); }}
  .post-card summary {{ padding: 1rem 1.2rem; cursor: pointer; display: flex;
                         align-items: center; gap: .75rem; list-style: none; }}
  .post-card summary::-webkit-details-marker {{ display: none; }}
  .post-card summary::before {{ content: "▶"; font-size: .7rem; color: var(--muted);
                                 transition: transform .2s; }}
  .post-card[open] summary::before {{ transform: rotate(90deg); }}
  .post-card > div, .post-card > p {{ padding: 0 1.2rem 1.2rem; }}
  .post-num {{ background: #1a1a2e; color: #fff; border-radius: 4px;
               padding: .2rem .5rem; font-size: .8rem; flex-shrink: 0; }}
  .post-title {{ flex: 1; font-weight: 600; }}
  .post-title a {{ color: var(--text); text-decoration: none; }}
  .post-title a:hover {{ color: var(--accent); }}
  .reasons {{ display: flex; gap: .4rem; flex-wrap: wrap; }}
  .badge {{ font-size: .7rem; color: #fff; border-radius: 4px;
             padding: .15rem .5rem; white-space: nowrap; }}
  .metrics-row {{ display: flex; gap: .75rem; flex-wrap: wrap;
                  padding: .75rem 1.2rem; background: var(--bg);
                  border-top: 1px solid var(--border); border-bottom: 1px solid var(--border); }}
  .pill {{ display: flex; flex-direction: column; align-items: center;
           background: var(--card); border: 1px solid var(--border);
           border-radius: 6px; padding: .4rem .8rem; min-width: 80px; }}
  .pill-label {{ font-size: .7rem; color: var(--muted); }}
  .pill-value {{ font-size: 1.1rem; font-weight: 700; }}
  .summary-box {{ background: #fffbf0; border-left: 4px solid #f39c12;
                  padding: .75rem 1rem; border-radius: 0 6px 6px 0;
                  margin-bottom: 1rem; font-size: .95rem; }}
  .placement {{ background: #eaf4fb; color: #2980b9; font-size: .75rem;
                border-radius: 4px; padding: .15rem .5rem; }}
  ol, ul {{ padding-left: 1.4rem; }}
  li {{ margin-bottom: .6rem; }}
  code {{ background: #f3f4f5; padding: .1rem .35rem; border-radius: 3px;
          font-size: .9em; }}
  small {{ color: var(--muted); }}
  .error {{ color: #e74c3c; font-style: italic; padding: 1rem 0; }}
  a {{ color: var(--accent); }}
  .rm-panel {{ background: #f0f7ff; border: 1px solid #c8e0f7; border-radius: 6px;
               padding: .75rem 1rem; margin-bottom: 1rem; }}
  .rm-grid {{ display: flex; flex-direction: column; gap: .35rem; margin-top: .4rem; }}
  .rm-row {{ display: flex; gap: .75rem; font-size: .875rem; }}
  .rm-label {{ color: var(--muted); min-width: 130px; flex-shrink: 0; }}
  .rm-val {{ word-break: break-word; }}
</style>
</head>
<body>
<header>
  <h1>SEO Opportunity Report</h1>
  <p>{site} &nbsp;·&nbsp; Generated {date.today().isoformat()}</p>
  <div class="stats">
    <div class="stat">
      <div class="stat-val">{len(results)}</div>
      <div class="stat-label">Posts Flagged</div>
    </div>
    <div class="stat">
      <div class="stat-val">{analyzed}</div>
      <div class="stat-label">AI-Analyzed</div>
    </div>
    <div class="stat">
      <div class="stat-val">{sum(int(r['metrics']['impressions']) for r in results):,}</div>
      <div class="stat-label">Total Impressions</div>
    </div>
    <div class="stat">
      <div class="stat-val">{sum(int(r['metrics']['clicks']) for r in results):,}</div>
      <div class="stat-label">Total Clicks</div>
    </div>
  </div>
</header>
<main>
  <h2>Overview — All Flagged Posts</h2>
  <table>
    <thead>
      <tr>
        <th>#</th><th>Post</th><th>Impressions</th>
        <th>Clicks</th><th>CTR</th><th>Avg Position</th>
      </tr>
    </thead>
    <tbody>{overview_rows}</tbody>
  </table>

  <h2>Post-by-Post Analysis</h2>
  <p style="color:var(--muted);font-size:.85rem;margin-bottom:1rem">
    Click any post to expand the full SEO recommendations.
  </p>
  {post_sections}
</main>
</body>
</html>"""

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    return output_path
