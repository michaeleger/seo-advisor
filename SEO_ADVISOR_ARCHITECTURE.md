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
│                 4. WP PUBLISHER / PASTE-BACK HELPER                     │
│  - Option A: Manual copy/paste into WP Admin & Rank Math Meta Box       │
│  - Option B: Zero-Cost Helper Script (applies Chat JSON via WP REST)    │
└────────────────────────────────────┴────────────────────────────────────┘
```

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
| **WordPress Client** | [wp_client.py](file:///home/aiuser/projects/seo-advisor/wp_client.py) | **Keep & Extend**: Reads content + Rank Math meta; can be extended for zero-cost writeback. |
| **Rank Math REST Bridge** | [eager-rankmath-rest.php](file:///home/aiuser/projects/seo-advisor/wordpress-plugin/eager-rankmath-rest.php) | **Keep**: Exposes native Rank Math postmeta fields reliably via REST. |
| **Report Generator** | [briefing.py](file:///home/aiuser/projects/seo-advisor/briefing.py) | **Primary Upgrade Focus**: Formats the Markdown payload for maximum Grok/Claude usability. |
| **PageSpeed Insights** | [pagespeed.py](file:///home/aiuser/projects/seo-advisor/pagespeed.py) | **Keep**: Runs free Lighthouse/CrUX scans on selected URLs only. |
| **Search Console Client** | [gsc.py](file:///home/aiuser/projects/seo-advisor/gsc.py) | **Keep**: Pulls site & page queries, cannibalization, and performance trends. |

---

## 3. Recommended Improvements for the Zero-Cost Model

### Improvement 1: Streamline Markdown Report for Chat Context Windows
**Problem**: Large HTML body dumps exceed LLM chat context limits or cause cluttered responses.
**Solution**: Refine [briefing.py](file:///home/aiuser/projects/seo-advisor/briefing.py#L66-L150) to output:
- Concise content structure (H1, H2s, H3s, first 300 words, last 200 words, total word count).
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

### Improvement 3: Zero-Cost "Paste-Back" Import Script
To avoid manually copying title, description, and focus keyword into WordPress inputs one-by-one:
- Add a lightweight zero-cost script (`apply_chat_response.py`).
- After Grok/Claude outputs the JSON block in chat, paste it into `latest_response.json` and run:
  ```bash
  python apply_chat_response.py latest_response.json
  ```
- The script uses [wp_client.py](file:///home/aiuser/projects/seo-advisor/wp_client.py) / Application Passwords or [eager-rankmath-rest.php](file:///home/aiuser/projects/seo-advisor/wordpress-plugin/eager-rankmath-rest.php) to update `rank_math_title`, `rank_math_description`, and `rank_math_focus_keyword` in WordPress automatically. WordPress and Rank Math immediately recalculate the live score on save!

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
2. **Optimize `briefing.py`**: Refine the generated Markdown report to format content and metrics compactly for chat prompts.
3. **Enhance Chat Handoff Prompt**: Prompt Grok/Claude to output clean JSON metadata blocks alongside the rewritten HTML.
4. **Add Zero-Cost Writeback Helper**: Create `apply_chat_response.py` to push chat-generated Rank Math JSON metadata back into WordPress via REST API.
