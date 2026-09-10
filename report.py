"""Generate a self-contained HTML SEO report."""
import html
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
        f'<span class="pill-value" style="color:{color}">{value}</span>'
        f'<span class="pill-delta">{delta}</span>'
        f"</div>"
    )


def _reason_tags(reasons: list[str]) -> str:
    return " ".join(_badge(r, "#e74c3c") for r in reasons)


def _delta_span(new_val: float, old_val: float | None, fmt: str = "+.0f", invert: bool = False) -> str:
    if old_val is None:
        return ""
    diff = new_val - old_val
    if diff == 0:
        return '<span style="color:#888;font-size:.8em"> (=)</span>'
    good = (diff < 0) if invert else (diff > 0)
    color = "#2ecc71" if good else "#e74c3c"
    sign = "+" if diff > 0 else ""
    return f'<span style="color:{color};font-size:.8em;margin-left:.3em">({sign}{diff:{fmt.lstrip("+")}})</span>'


def _keyword_opportunities_section(analysis: dict) -> str:
    keywords = analysis.get("target_keywords", [])
    if not keywords:
        return ""

    intent_colors = {
        "informational": "#3498db",
        "navigational": "#9b59b6",
        "transactional": "#27ae60",
        "commercial": "#e67e22",
    }

    rows = ""
    for k in keywords:
        intent = k.get("intent", "informational").lower()
        color = intent_colors.get(intent, "#888")
        intent_badge = f'<span class="badge" style="background:{color};font-size:.65rem">{intent}</span>'
        rows += (
            f"<tr>"
            f'<td><code class="kw">{k["keyword"]}</code> {intent_badge}</td>'
            f"<td>{k['rationale']}</td>"
            f"</tr>"
        )

    meta_desc = analysis.get("meta_description", "")
    meta_row = ""
    if meta_desc:
        char_count = len(meta_desc)
        color = "#27ae60" if 140 <= char_count <= 160 else "#e67e22"
        meta_row = f"""
    <div class="meta-desc-box">
      <div class="section-label">Suggested Meta Description
        <span style="color:{color};font-size:.8rem;margin-left:.5rem">({char_count} chars)</span>
      </div>
      <p class="meta-desc-text">{meta_desc}</p>
    </div>"""

    evergreen = analysis.get("is_evergreen")
    evergreen_html = ""
    if evergreen is not None:
        icon = "🌿" if evergreen else "📅"
        label = "Evergreen content" if evergreen else "Time-sensitive content"
        rationale = analysis.get("evergreen_rationale", "")
        ev_color = "#27ae60" if evergreen else "#e67e22"
        rationale_html = f' <span class="ev-note">— {rationale}</span>' if rationale else ""
        evergreen_html = (
            f'<div class="evergreen-tag" style="border-color:{ev_color};color:{ev_color}">'
            f'{icon} {label}{rationale_html}'
            f'</div>'
        )

    return f"""
    <div class="section-block kw-section">
      <h4 class="section-heading">Keyword Opportunities</h4>
      {evergreen_html}
      <table>
        <thead><tr><th>Keyword</th><th>Why it fits</th></tr></thead>
        <tbody>{rows}</tbody>
      </table>
      {meta_row}
    </div>"""


def _phrases_section(phrases: list[dict]) -> str:
    if not phrases:
        return ""
    rows = "".join(
        f'<tr><td><em>&ldquo;{p["phrase"]}&rdquo;</em></td>'
        f'<td><span class="placement">{p["placement"]}</span></td></tr>'
        for p in phrases
    )
    return f"""
    <div class="section-block">
      <h4 class="section-heading">Phrases to Add</h4>
      <table>
        <thead><tr><th>Phrase</th><th>Where</th></tr></thead>
        <tbody>{rows}</tbody>
      </table>
    </div>"""


def _title_section(titles: list[dict]) -> str:
    if not titles:
        return ""
    items = "".join(
        f"<li><strong>{t['title']}</strong><br><small class='muted'>{t['rationale']}</small></li>"
        for t in titles
    )
    return f"""
    <div class="section-block">
      <h4 class="section-heading">Title Suggestions</h4>
      <ol class="title-list">{items}</ol>
    </div>"""


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
      <h4 class="section-heading" style="margin-top:0">RankMath Snapshot</h4>
      <div class="rm-grid">
        <div class="rm-row"><span class="rm-label">Focus Keyword</span><span class="rm-val"><code>{kw}</code></span></div>
        <div class="rm-row"><span class="rm-label">SEO Score</span><span class="rm-val">{score_html}</span></div>
        <div class="rm-row"><span class="rm-label">Meta Title</span><span class="rm-val">{mt}</span></div>
        <div class="rm-row"><span class="rm-label">Meta Description</span><span class="rm-val">{md}</span></div>
      </div>
    </div>"""


def _reco_section(recos: list[dict]) -> str:
    if not recos:
        return ""
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
    return f"""
    <div class="section-block">
      <h4 class="section-heading">Content Recommendations</h4>
      <ul class="reco-list">{''.join(items)}</ul>
    </div>"""


def _queries_section(queries: list[dict] | None) -> str:
    queries = queries or []
    if not queries:
        return ""
    rows = "".join(
        f"<tr>"
        f'<td><code class="kw">{html.escape(str(q.get("query") or ""))}</code></td>'
        f"<td>{int(q.get('impressions') or 0)}</td>"
        f"<td>{int(q.get('clicks') or 0)}</td>"
        f"<td>{float(q.get('ctr') or 0) * 100:.1f}%</td>"
        f"<td>{float(q.get('position') or 0):.1f}</td>"
        f"</tr>"
        for q in queries[:15]
    )
    return f"""
    <div class="section-block">
      <h4 class="section-heading">Top GSC Queries</h4>
      <table>
        <thead><tr><th>Query</th><th>Impr</th><th>Clicks</th><th>CTR</th><th>Pos</th></tr></thead>
        <tbody>{rows}</tbody>
      </table>
    </div>"""


def _pagespeed_section(ps: dict | None) -> str:
    if not ps:
        return ""
    if not ps.get("ok"):
        if ps.get("error"):
            return (
                '<div class="section-block"><h4 class="section-heading">PageSpeed</h4>'
                f'<p class="muted">Scan failed: {html.escape(str(ps.get("error")))}</p></div>'
            )
        return ""

    blocks = []
    for strat, b in (ps.get("strategies") or {}).items():
        sc = b.get("scores") or {}
        pills = "".join(
            f'<span class="placement">{lbl}: {val if val is not None else "&mdash;"}</span> '
            for lbl, val in (
                ("perf", sc.get("performance")),
                ("a11y", sc.get("accessibility")),
                ("best practices", sc.get("best_practices")),
                ("seo", sc.get("seo")),
            )
        )
        lab = (b.get("lab") or {}).get("core_metrics") or {}
        lab_bits = ", ".join(
            f"{mid.upper()} {lab[mid]['display_value']}"
            for mid in ("lcp", "cls", "tbt", "fcp")
            if lab.get(mid) and lab[mid].get("display_value")
        )
        lab_html = f'<p class="muted">Lab: {html.escape(lab_bits)}</p>' if lab_bits else ""
        issues = (b.get("lab") or {}).get("html_relevant_issues") or []
        issue_items = "".join(
            f"<li>{html.escape(str(i.get('title') or i.get('id') or ''))}"
            + (
                f" &mdash; {html.escape(str(i.get('display_value')))}"
                if i.get("display_value")
                else ""
            )
            + "</li>"
            for i in issues[:8]
        )
        issue_html = (
            f'<ul class="reco-list">{issue_items}</ul>' if issue_items else ""
        )
        blocks.append(
            f'<div style="margin-bottom:.7rem"><strong>{html.escape(str(strat))}</strong>'
            f'<br>{pills}{lab_html}{issue_html}</div>'
        )
    return f"""
    <div class="section-block">
      <h4 class="section-heading">PageSpeed (selected-page scan)</h4>
      {''.join(blocks)}
    </div>"""


def _post_section(idx: int, metrics: dict, post: dict, analysis: dict | None,
                  prev_metrics: dict | None = None,
                  queries: list[dict] | None = None,
                  pagespeed: dict | None = None) -> str:
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
    queries_block = _queries_section(queries)
    pagespeed_block = _pagespeed_section(pagespeed)

    if analysis:
        summary = analysis.get("summary") or ""
        summary_html = f'<div class="summary-box">{html.escape(summary)}</div>' if summary else ""
        body = f"""
        {rm_panel}
        {summary_html}
        {_keyword_opportunities_section(analysis)}
        {_title_section(analysis.get('title_suggestions', []))}
        {_phrases_section(analysis.get('phrases_to_add', []))}
        {_reco_section(analysis.get('content_recommendations', []))}
        {queries_block}
        {pagespeed_block}
        """
    else:
        body = f"{rm_panel}{queries_block}{pagespeed_block}"
        rm_has_data = any((post.get("rankmath") or {}).values())
        if not (queries_block or pagespeed_block or rm_has_data):
            body += (
                '<p class="hint">No WordPress / GSC / PageSpeed enrichment for '
                "this page yet — see the Markdown briefing for full context.</p>"
            )

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
      <div class="post-body">{body}</div>
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
        _post_section(
            i + 1, r["metrics"], r["post"], r.get("analysis"),
            r.get("prev_metrics"), r.get("queries"), r.get("pagespeed"),
        )
        for i, r in enumerate(results)
    )

    any_analysis = any(r.get("analysis") for r in results)
    analyzed = sum(1 for r in results if r.get("analysis"))
    total_kw = sum(
        len(r["analysis"].get("target_keywords", []))
        for r in results if r.get("analysis")
    )

    first_url = (results[0]["post"].get("url") or "") if results else ""
    _parts = first_url.split("/")
    site = _parts[2] if len(_parts) > 2 else "your site"

    ai_stats = ""
    if any_analysis:
        ai_stats = f"""
    <div class="stat">
      <div class="stat-val">{analyzed}</div>
      <div class="stat-label">AI-Analyzed</div>
    </div>
    <div class="stat">
      <div class="stat-val">{total_kw}</div>
      <div class="stat-label">Keywords Found</div>
    </div>"""

    expand_hint = (
        "Click any post to expand keyword opportunities, title rewrites, "
        "and content improvements."
        if any_analysis
        else "Click any post to expand RankMath status, top GSC queries, and "
        "PageSpeed findings. Full keyword strategy lives in the Markdown "
        "briefing (reports/seo_report_*.md)."
    )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>SEO Report — {site}</title>
<style>
  :root {{
    --bg: #f5f6fa;
    --card: #fff;
    --border: #e1e4e8;
    --text: #24292e;
    --muted: #586069;
    --accent: #0366d6;
    --radius: 8px;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    background: var(--bg);
    color: var(--text);
    line-height: 1.65;
    font-size: 15px;
  }}

  /* ── Header ── */
  header {{ background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%); color: #fff; padding: 2rem 2.5rem; }}
  header h1 {{ font-size: 1.7rem; font-weight: 700; margin-bottom: .3rem; letter-spacing: -.02em; }}
  header p {{ color: #9aa5b4; font-size: .9rem; }}
  .stats {{ display: flex; gap: 1rem; margin-top: 1.2rem; flex-wrap: wrap; }}
  .stat {{
    background: rgba(255,255,255,.08);
    border: 1px solid rgba(255,255,255,.12);
    border-radius: var(--radius);
    padding: .7rem 1.3rem;
    text-align: center;
    min-width: 110px;
  }}
  .stat-val {{ font-size: 1.8rem; font-weight: 700; line-height: 1; }}
  .stat-label {{ font-size: .72rem; color: #9aa5b4; text-transform: uppercase; letter-spacing: .06em; margin-top: .2rem; }}

  /* ── Main layout ── */
  main {{ max-width: 1000px; margin: 2rem auto; padding: 0 1.25rem; }}

  /* ── Section headings ── */
  h2 {{
    font-size: 1.05rem;
    font-weight: 700;
    margin: 2.5rem 0 1rem;
    padding-bottom: .5rem;
    border-bottom: 2px solid var(--border);
    text-transform: uppercase;
    letter-spacing: .06em;
    color: var(--muted);
  }}
  .section-heading {{
    font-size: .75rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: .07em;
    color: var(--muted);
    margin: 1.4rem 0 .6rem;
  }}

  /* ── Overview table ── */
  table {{ width: 100%; border-collapse: collapse; font-size: .88rem; margin-bottom: 1rem; }}
  th {{
    background: var(--bg);
    text-align: left;
    padding: .55rem .8rem;
    font-size: .75rem;
    color: var(--muted);
    border-bottom: 2px solid var(--border);
    text-transform: uppercase;
    letter-spacing: .05em;
  }}
  td {{ padding: .55rem .8rem; border-bottom: 1px solid var(--border); vertical-align: top; }}
  td.warn {{ color: #e74c3c; font-weight: 600; }}
  tr:hover td {{ background: #fafbfc; }}

  /* ── Post cards ── */
  .post-card {{
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    margin-bottom: 1rem;
    box-shadow: 0 1px 4px rgba(0,0,0,.05);
    transition: box-shadow .15s;
  }}
  .post-card:hover {{ box-shadow: 0 3px 10px rgba(0,0,0,.09); }}
  .post-card summary {{
    padding: 1rem 1.25rem;
    cursor: pointer;
    display: flex;
    align-items: center;
    gap: .75rem;
    list-style: none;
    user-select: none;
  }}
  .post-card summary::-webkit-details-marker {{ display: none; }}
  .post-card summary::before {{
    content: "▶";
    font-size: .65rem;
    color: var(--muted);
    transition: transform .2s;
    flex-shrink: 0;
  }}
  .post-card[open] summary::before {{ transform: rotate(90deg); }}
  .post-num {{
    background: #1a1a2e;
    color: #fff;
    border-radius: 4px;
    padding: .2rem .55rem;
    font-size: .78rem;
    font-weight: 700;
    flex-shrink: 0;
  }}
  .post-title {{ flex: 1; font-weight: 600; font-size: .95rem; }}
  .post-title a {{ color: var(--text); text-decoration: none; }}
  .post-title a:hover {{ color: var(--accent); }}
  .reasons {{ display: flex; gap: .35rem; flex-wrap: wrap; }}

  /* ── Metrics pills ── */
  .metrics-row {{
    display: flex;
    gap: .6rem;
    flex-wrap: wrap;
    padding: .75rem 1.25rem;
    background: var(--bg);
    border-top: 1px solid var(--border);
    border-bottom: 1px solid var(--border);
  }}
  .pill {{
    display: flex;
    flex-direction: column;
    align-items: center;
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: .45rem .9rem;
    min-width: 88px;
  }}
  .pill-label {{ font-size: .68rem; color: var(--muted); text-transform: uppercase; letter-spacing: .05em; }}
  .pill-value {{ font-size: 1.15rem; font-weight: 700; line-height: 1.2; }}
  .pill-delta {{ font-size: .72rem; color: var(--muted); min-height: 1em; }}

  /* ── Post body ── */
  .post-body {{ padding: 1rem 1.25rem 1.25rem; }}
  .section-block {{ margin-bottom: 1.5rem; }}

  /* ── Summary box ── */
  .summary-box {{
    background: #fffbf0;
    border-left: 4px solid #f39c12;
    padding: .85rem 1.1rem;
    border-radius: 0 6px 6px 0;
    margin-bottom: 1.2rem;
    font-size: .95rem;
    line-height: 1.7;
  }}

  /* ── Keyword opportunities ── */
  .kw-section {{ background: #f8f9fe; border: 1px solid #dde4f7; border-radius: 6px; padding: .9rem 1.1rem; }}
  code.kw {{ background: #e8edf8; color: #1a3a8f; padding: .1rem .4rem; border-radius: 3px; font-size: .88em; }}
  .evergreen-tag {{
    display: inline-flex;
    align-items: center;
    gap: .4rem;
    border: 1px solid;
    border-radius: 20px;
    padding: .2rem .75rem;
    font-size: .8rem;
    font-weight: 600;
    margin-bottom: .75rem;
  }}
  .ev-note {{ font-weight: 400; color: var(--muted); }}

  /* ── Meta description box ── */
  .meta-desc-box {{
    margin-top: 1rem;
    background: #fff;
    border: 1px dashed #b0c4de;
    border-radius: 6px;
    padding: .75rem 1rem;
  }}
  .section-label {{ font-size: .72rem; font-weight: 700; color: var(--muted); text-transform: uppercase; letter-spacing: .06em; margin-bottom: .4rem; }}
  .meta-desc-text {{ font-size: .9rem; color: var(--text); line-height: 1.6; }}

  /* ── Title list ── */
  .title-list {{ padding-left: 1.2rem; }}
  .title-list li {{ margin-bottom: .9rem; }}
  .title-list strong {{ font-size: .95rem; }}
  .muted {{ color: var(--muted); font-size: .85rem; }}

  /* ── Reco list ── */
  .reco-list {{ list-style: none; padding: 0; }}
  .reco-list li {{ margin-bottom: .7rem; display: flex; align-items: flex-start; gap: .5rem; line-height: 1.55; }}

  /* ── Phrases table ── */
  .placement {{
    background: #eaf4fb;
    color: #1a6fa8;
    font-size: .72rem;
    border-radius: 4px;
    padding: .15rem .5rem;
    white-space: nowrap;
    font-weight: 600;
  }}

  /* ── RankMath panel ── */
  .rm-panel {{
    background: #f0f7ff;
    border: 1px solid #c8e0f7;
    border-radius: 6px;
    padding: .75rem 1rem;
    margin-bottom: 1.1rem;
  }}
  .rm-grid {{ display: flex; flex-direction: column; gap: .4rem; margin-top: .5rem; }}
  .rm-row {{ display: flex; gap: .75rem; font-size: .875rem; }}
  .rm-label {{ color: var(--muted); min-width: 130px; flex-shrink: 0; font-weight: 500; }}
  .rm-val {{ word-break: break-word; }}

  /* ── Misc ── */
  .badge {{
    font-size: .68rem;
    color: #fff;
    border-radius: 4px;
    padding: .15rem .5rem;
    white-space: nowrap;
    font-weight: 600;
    flex-shrink: 0;
  }}
  code {{ background: #f3f4f5; padding: .1rem .35rem; border-radius: 3px; font-size: .88em; }}
  a {{ color: var(--accent); }}
  .error {{ color: #e74c3c; font-style: italic; padding: 1rem 0; }}
  .hint {{ color: var(--muted); font-size: .85rem; margin-bottom: 1rem; }}
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
    {ai_stats}
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
  <p class="hint">{expand_hint}</p>
  {post_sections}
</main>
</body>
</html>"""

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    return output_path
