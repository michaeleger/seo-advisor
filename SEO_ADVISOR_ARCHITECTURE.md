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
5. **The Reader Outranks the Score**: Every metric in this tool is a *diagnostic*, never a specification. Rewrites are written for a person who arrived with a question. A human editor reviews each one and **rejects copy that reads as though it was written for a search engine or an answer engine** — padded word counts, repeated keywords, headings and FAQ blocks bolted on to satisfy a checklist. A page that scores 70 and reads well beats a page that scores 95 and reads like it was assembled for a crawler. Where satisfying a Rank Math rule would make a page worse to read, the rule loses.
6. **The Live Page Is the Source of Truth**: The report carries measurements about a page, never a copy of it. The model reads the published URL for content, markup, images and styling.

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
- Heading outline (H1–H6) and total word count.
- **No article text.** The published page is the source of truth for content,
  markup, images and styling; the prompt sends the model to the live URL.
  A stripped copy in the report would be a degraded duplicate.
- Paragraph count and how many exceed Rank Math's long-paragraph threshold;
  image count and how many lack alt text; internal / external /
  external-dofollow link counts.
- A **"Rank Math diagnostics (observations, not targets)"** line naming the
  plugin rules the page currently misses, measurement first (see Improvement 2
  revised).
- Exact list of low-CTR GSC keywords for the page.
- Specific Lighthouse accessibility / speed issues affecting HTML markup (e.g., missing alt text, non-descriptive link anchors, tap target spacing).

### ~~Improvement 2: Standardize Dual-Output Format for Grok & Claude~~
~~Update the embedded prompt template to instruct Grok or Claude to return **two precise code blocks per page**.~~

> **Superseded.** We do **not** standardize the output format — pinning a
> schema here is the same mistake as pinning a design system.

### Improvement 2 (revised): Delegate Format and Design Standards — ✅ DONE
**Principle**: the payload format (HTML, metadata JSON, CSS, images) and every
design decision belong to the **AI model**, formatted to whatever standards are
current when the rewrite happens. Standards change; this repo must not freeze
them.

**Scope**: the tool prompts a **rewrite and update** of each page — a complete,
publication-ready replacement — not an SEO tweak list.

The prompt in `briefing.py` therefore draws a hard line:

| This repo supplies | The model decides |
|---|---|
| GSC / Bing / Planner metrics | Which artifacts to return, and their shape |
| Rank Math score + rubric misses | Markup, semantics, accessibility, responsive behaviour |
| PageSpeed lab + CrUX defects | Typography, layout, component structure |
| Structural measurements + the live URL | Image formats, sizing, art direction |

It instructs the model to apply the standards current as of its own knowledge,
and to override how the page is built today where the two conflict.

**Constraints that remain real** (these are facts, not fashions): use only the
briefing's data, preserve the article's factual substance, introduce no
unsupported health claims, keep the URL unless flagged separately, and fix the
causes of PageSpeed defects.

**Rank Math thresholds** (`_RM_MIN_WORDS`, `_RM_LONG_PARAGRAPH_WORDS`) are the
one exception, and they are quarantined: named constants, documented as the
plugin's scoring rubric, rendered as `"707 words (Rank Math wants ≥600)"` so
the measurement leads and the threshold is attributed. A rubric change dates
the label, not the fact.

They are also **rendered as diagnostics, never as targets** — see Pillar 5.
The prompt states outright that satisfying one is optional where it would hurt
the reading experience, and asks the model to say why it left one unmet.
Instructing a model to "clear" a rubric is what produces padded, link-stuffed
copy; the human reviewer rejects that, so the tool must not ask for it.

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
   link/image counts) plus a per-page "Rank Math diagnostics" line replace the
   truncated excerpt. Content itself is read from the live page, not shipped.
3. ✅ **Chat Handoff Prompt**: asks for a full page rewrite and delegates output
   format and design standards to the model. Deliberately schema-free — the
   payload shape is not pinned by this repo.
4. ❌ **Write-back helper**: dropped. `wp.py` handles write-back outside this
   repo; nothing here writes to WordPress.
