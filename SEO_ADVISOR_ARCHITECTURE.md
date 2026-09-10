# SEO Advisor — Zero-API-Cost Architecture & Refactoring Guide

> **Project Goal**: Maximize organic search improvements on high-upside pages, preserve the complete Rank Math metadata structure and scoring integrity, reuse existing Rank Math tools, and operate at **zero API cost** via a report-based handoff to Grok or Claude chat.

---

## 1. Core Architectural Principles

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    1. LOCAL DATA HARVESTER (FREE)                       │
│  - WP REST Reader (Rank Math Meta: title, desc, focus KW, score)        │
│  - Google Search Console API (Free OAuth - Clicks, Impr, CTR, Pos)      │
│  - PageSpeed Insights API (Free Key - Core Web Vitals & Lighthouse)     │
│  - Bing Webmaster API (Free Key - Search Queries & Pages)              │
└────────────────────────────────────┬────────────────────────────────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                   2. LEAN REPORT GENERATOR (LOCAL)                      │
│  - Filters Improvable Pages First (Rank Math Score <80 + GSC Upside)    │
│  - Extracts Content Snippets, Heading Tree & Lighthouse Audits          │
│  - Produces: reports/seo_report_YYYY-MM-DD.md                           │
└────────────────────────────────────┬────────────────────────────────────┘
                                     │  (Zero API Cost - Manual Copy/Paste)
                                     ▼
┌─────────────────────────────────────────────────────────────────────────┐
│              3. CHAT MODEL ENGINE (Grok 3 or Claude Web UI)             │
│  - Reads Markdown Report + Embedded Prompt                              │
│  - Generates Optimized HTML Content & Rank Math Meta Block              │
└────────────────────────────────────┬────────────────────────────────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────────┐
│            4. WRITE-BACK — EXTERNAL, NOT PART OF THIS REPO              │
│  - A premade REST script (wp.py) applies the chat output to             │
│    WordPress: page content + Rank Math meta                             │
│  - Run by hand, outside this pipeline                                   │
└────────────────────────────────────┴────────────────────────────────────┘
```

> **Scope boundary:** SEO Advisor's job ends at
> `reports/seo_report_YYYY-MM-DD.md`. It never writes to WordPress. A human
> feeds the report to the chat model and applies the result with `wp.py`.
> Everything in this repo — including the mu-plugin — is **read-only**
> against the site.

### Key Pillars:
1. **Zero API Expenses**: No paid Anthropic, OpenAI, or xAI API keys required. All data sources use free tiers (GSC OAuth, PageSpeed Insights API key, Bing API key, WordPress REST).
2. **Rank Math Metadata Integrity**: Preserves native WP postmeta fields (`rank_math_title`, `rank_math_description`, `rank_math_focus_keyword`, `rank_math_robots`, `rank_math_schema_*`). Past work product remains 100% intact.
3. **Reusing Existing Rank Math Tools**: Leverages [eager-rankmath-rest.php](file:///home/aiuser/projects/seo-advisor/wordpress-plugin/eager-rankmath-rest.php) and [wp_client.py](file:///home/aiuser/projects/seo-advisor/wp_client.py) to read and expose native Rank Math plugin scores without slow or inaccurate third-party scrapers.
4. **Rank Math Improvable-First Prioritization**: Focuses processing energy strictly on posts scoring under **80/100** in Rank Math, sorted by score tiers (`<20` critical ➔ `20-39` poor ➔ `40-59` fair ➔ `60-79` improvable).

---

## 2. Examination of Current Implementation

| Component | Current File | Status & Role in Zero-Cost Model |
|---|---|---|
| **Pipeline Controller** | [main.py](file:///home/aiuser/projects/seo-advisor/main.py) | **Keep & Refine**: Orchestrates stages, generates reports for chat handoff. |
| **Improvable Analyzer** | [analyzer.py](file:///home/aiuser/projects/seo-advisor/analyzer.py) | **Keep & Refine**: Implements Rank Math score tiers + GSC opportunity ranking. |
| **WordPress Client** | [wp_client.py](file:///home/aiuser/projects/seo-advisor/wp_client.py) | **Keep**: Read-only. Reads content + Rank Math meta and summarizes content structure. Write-back is external (`wp.py`). |
| **Rank Math REST Bridge** | [eager-rankmath-rest.php](file:///home/aiuser/projects/seo-advisor/wordpress-plugin/eager-rankmath-rest.php) | **Keep**: Exposes native Rank Math postmeta fields reliably via REST. |
| **Report Generator** | [briefing.py](file:///home/aiuser/projects/seo-advisor/briefing.py) | **Primary Upgrade Focus**: Formats the Markdown payload for maximum Grok/Claude usability. |
| **PageSpeed Insights** | [pagespeed.py](file:///home/aiuser/projects/seo-advisor/pagespeed.py) | **Keep**: Runs free Lighthouse/CrUX scans on selected URLs only. |
| **Search Console Client** | [gsc.py](file:///home/aiuser/projects/seo-advisor/gsc.py) | **Keep**: Pulls site & page queries, cannibalization, and performance trends. |

---

## 3. Recommended Improvements for the Zero-Cost Model

### Improvement 1: Streamline Markdown Report for Chat Context Windows — ✅ DONE
**Problem**: Large HTML body dumps exceed LLM chat context limits or cause cluttered responses.
**Implemented**: `wp_client.content_structure()` summarizes the rendered HTML and
`briefing.py` renders it per page:
- Heading outline (H1–H6), total word count, first 300 / last 200 words
  (short posts pass through whole).
- Paragraph count and how many exceed 120 words; image count and how many
  lack alt text; internal / external / external-dofollow link counts.
- A **"Rank Math gaps"** line naming the rules the page currently fails.
- Exact list of low-CTR GSC keywords for the page.
- Specific Lighthouse accessibility / speed issues affecting HTML markup (e.g., missing alt text, non-descriptive link anchors, tap target spacing).

### Improvement 2: Standardize Dual-Output Format for Grok & Claude
Update the embedded prompt template in [briefing.py](file:///home/aiuser/projects/seo-advisor/briefing.py#L12-L45) to instruct Grok or Claude to return **two precise code blocks per page**:

1. **Rank Math Metadata Block** (JSON format for instant review or paste-back):
```json
{
  "post_id": 1234,
  "url": "https://www.eagertobehealthy.com/example-post/",
  "rank_math_focus_keyword": "primary keyword phrase",
  "rank_math_title": "Optimized Title Tag (50-60 chars)",
  "rank_math_description": "Compelling Meta Description with CTA (120-155 chars)",
  "rank_math_secondary_keywords": ["keyword 2", "keyword 3"]
}
```

2. **Updated HTML Content Block**:
- Complete, publication-ready clean HTML incorporating improved headings, target keywords in the first 10% of body text, and fixed image alt tags.

> **Status: pending.** The exact field names above are a placeholder. Both
> blocks must match whatever `wp.py` consumes, so this prompt rewrite is
> blocked until that script's expected input format is confirmed.

### Improvement 3: Write-Back — Out of Scope (handled by `wp.py`)
**Decision:** this repo does **not** build a paste-back importer. An earlier
draft proposed an `apply_chat_response.py` helper plus write endpoints on the
mu-plugin; both were dropped.

Write-back is done with a **premade REST script (`wp.py`)** that already exists
outside this project and updates page content and Rank Math meta
(`rank_math_title`, `rank_math_description`, `rank_math_focus_keyword`).
WordPress and Rank Math recalculate the live score on save.

Consequences for this repo:
- `wp_client.py` and `eager-rankmath-rest.php` stay **read-only**.
- No credentials with write scope are needed by the pipeline.
- The handoff stays manual: a human pastes the report into the chat model
  and runs `wp.py` on the result.

---

## 4. Preservation of Rank Math Metadata & Scoring Rubric

To ensure past work is preserved and Rank Math tools remain fully compatible:

```
                          Rank Math Scoring Rubric (100 Points)
┌──────────────────────────────────────────────────────────────────────────────────────────┐
│ BASIC SEO (40 pts)                                                                       │
│  - Focus keyword in SEO Title                                                            │
│  - Focus keyword in Meta Description                                                     │
│  - Focus keyword in URL slug                                                             │
│  - Focus keyword in first 10% of content                                                 │
│  - Focus keyword found in content body                                                   │
│  - Content length >= 600 words                                                           │
├──────────────────────────────────────────────────────────────────────────────────────────┤
│ ADDITIONAL SEO (30 pts)                                                                  │
│  - Focus keyword in Subheadings (H2/H3/H4)                                               │
│  - Focus keyword in Image Alt attributes                                                 │
│  - Keyword density between 1% and 2.5%                                                   │
│  - Contains at least 1 internal link                                                     │
│  - Contains at least 1 external dofollow link                                            │
├──────────────────────────────────────────────────────────────────────────────────────────┤
│ TITLE READABILITY (15 pts)                                                               │
│  - Focus keyword used near beginning of title                                            │
│  - Title contains a number / power word                                                  │
├──────────────────────────────────────────────────────────────────────────────────────────┤
│ CONTENT READABILITY (15 pts)                                                             │
│  - Short paragraphs (<120 words)                                                         │
│  - Contains images or rich elements                                                      │
└──────────────────────────────────────────────────────────────────────────────────────────┘
```

The report generated for Grok/Claude chat specifically highlights which of these rules are currently failing for each page, allowing the model to target a **90+ Rank Math Score** on every rewrite.

---

## 5. Summary of Recommended Refactoring Steps for Agents

1. **Keep the zero-cost architecture**: Run data extraction locally via `./run.sh`.
2. ✅ **Optimize `briefing.py`**: content structure (heading outline, word count,
   link/image counts, opening + closing text) and a per-page "Rank Math gaps"
   line now replace the truncated excerpt.
3. ⏳ **Enhance Chat Handoff Prompt**: have Grok/Claude return a metadata block
   plus rewritten HTML — **blocked on `wp.py`'s expected input format**.
4. ❌ **Write-back helper**: dropped. `wp.py` handles write-back outside this
   repo; nothing here writes to WordPress.
