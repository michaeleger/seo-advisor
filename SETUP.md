# SEO Advisor — Setup Guide

## Pipeline (semi-automatic → Claude)

```
1) Rank the most neglected under-performing pages
   missed clicks (GSC) × neglect (time since edit) × fixability (Rank Math) × decay
        ↓
2) Enrich ONLY those pages
   WordPress + GSC slices + Bing + Keyword Planner
        ↓
3) PageSpeed scan ONLY those selected URLs
   (lab Lighthouse + CrUX field data when available)
        ↓
 reports/seo_report_YYYY-MM-DD.md
        ↓
 YOU paste into Claude → keywords + fresh HTML guidance
```

---

## How pages are ranked (neglected under-performance)

```
priority = missed clicks × neglect × fixability × decay
```

| Factor | What it measures | Knobs |
|--------|------------------|-------|
| **missed clicks** | GSC demand the page fails to capture: clicks lost to a weak CTR for its position, plus clicks available by ranking at `TARGET_POSITION`. Sized over `DATE_RANGE_DAYS` (reported as `clicks/yr` at 365, `clicks/<N>d` otherwise). | `DATE_RANGE_DAYS`, `TARGET_POSITION` |
| **neglect** | 1.0 for a page edited today, rising to `NEGLECT_MAX_MULTIPLIER` after `NEGLECT_FULL_DAYS` untouched. Unknown edit date = 1.0. | `NEGLECT_FULL_DAYS`, `NEGLECT_MAX_MULTIPLIER` |
| **fixability** | Modest multiplier from the Rank Math score: 1.0 (score 100) → 2.0 (score 0); unknown = 1.3. | — |
| **decay** | Up to 1.5× when impressions fall versus the prior adjacent window. | `DECAY_WINDOW_DAYS` |

Gates before ranking: pages under `MIN_IMPRESSIONS` are skipped (undiscovered,
not under-performing — unless `INCLUDE_ZERO_TRAFFIC_PAGES=1`); pages at or above
`RANKMATH_SKIP_SCORE` (default 80) are skipped; `SKIP_*` filters drop site furniture.

**Rank Math is not the sort key.** It measures SEO-form completeness, so a bio
or booking page scores ~9 forever and would otherwise top every run.

**Backoff:** a page suggested but not edited is deferred (`BACKOFF_DAYS`, default
`30,60,90,180`, last value is a cap) and always comes back. A detected edit holds
the page for `EDIT_COOLDOWN_DAYS` (default 90) so Google can reprocess it.

**Catalog budgets:** `WP_CATALOG_PER_TYPE_MAX` (default 2000) applies to posts and
pages separately; `WP_RANKMATH_MAX_ITEMS` (default 2000) caps the score overlay.
Truncation is logged. See `.env.example` for every knob and its default.

The score used is the **real Rank Math plugin score** (`rank_math_seo_score`),
**not** the Post Studio “Audit SEO” button (that is an LLM estimate).

### How we read the real score

| Method | Auth | Notes |
|--------|------|--------|
| **`GET /wp-json/rankmath/v1/links/posts`** | Application Password | **Preferred.** Filter `seo_score_range=bad\|good\|great\|no-score` |
| Public `wp/v2` post `meta` | none | Score **not** exposed by default |
| `POST /updateMeta` | App password | **Write** title/description/focus keyword only |
| `POST /updateSeoScore` | App password | **Write** scores into RankMath (not a read) |
| Post Studio “Audit SEO” | Claude | **LLM opinion**, not plugin score |

### Setup (Application Password — same as Post Studio)

1. WP Admin → Users → your user → **Application Passwords** → create one  
2. On 5by5 `.env`:

```bash
WP_APP_USER=your_wp_username
WP_APP_PASSWORD=xxxx xxxx xxxx xxxx xxxx xxxx
```

3. Verify:

```bash
cd ~/projects/seo-advisor && source .venv/bin/activate
python -c "import wp_client; ps=wp_client.list_content_with_rankmath(types=('posts',), per_type_max=5); print([(p['title'][:40], p['rankmath']) for p in ps])"
```

You should see `seo_score` integers and `score_source: rankmath_links_api`.

**Fallback:** install `wordpress-plugin/eager-rankmath-rest.php` as an mu-plugin if you prefer public REST meta instead of app passwords.

---

## PageSpeed Insights (selected pages only)

Free Google API. **Not** run sitewide — only after worst-N selection.

1. [Google Cloud Console](https://console.cloud.google.com/) → enable **PageSpeed Insights API**
2. Create an **API key** (restrict to PageSpeed Insights API if you like)
3. In `.env`:

```bash
USE_PAGESPEED=1
PAGESPEED_API_KEY=your_key
PAGESPEED_STRATEGIES=mobile
# or: mobile,desktop
```

`PAGESPEED_API_KEY` is required: without it the stage is skipped (anonymous quota
returns HTTP 429 for every URL), and a run stops scanning at the first 429. With a
key, ~10 mobile scans per run is fine for free tier use.

---

## Quick start

```bash
cd ~/projects/seo-advisor
source .venv/bin/activate   # must be .venv
./run.sh --no-cooldown
# paste: reports/seo_report_YYYY-MM-DD.md → Claude
```

---

## 1) Google Search Console (required)

Already working with `token.json` from `python authorize.py`.

**Collected automatically:**

| Layer | Data |
|-------|------|
| Site | Monthly trend, devices, countries, search appearance |
| Site | Query opportunities (low CTR / zero click / striking distance) |
| Site | Top queries → best landing page |
| Site | Cannibalization (query on multiple URLs) |
| Per worst page | Queries, period-over-period, devices, countries, monthly trend |
| Per page | WordPress excerpt + RankMath |

GSC = **your** performance only. It does **not** include market search volume or keyword difficulty.

---

## 2) Google Ads Keyword Planner (volume + competition)

Open a Google Ads account, then:

> **Gated:** keep this off until the Cloud project has **Basic** (or higher)
> Google Ads API access. As of Sep 2026, access levels live on the Cloud
> project (Google Ads API Overview), not Ads → API Center. Developer tokens
> are optional/ignored.

1. **Google Cloud** (same project as GSC / OAuth client) → enable **Google Ads API**
2. **Google Cloud** → Google Ads API **Overview** → apply for **Basic** access  
   (complete brand verification if asked). Ads → API Center is deprecated.
3. Note your **customer ID** (and manager ID if using MCC)
4. On 5by5 RDP:

```bash
cd ~/projects/seo-advisor && source .venv/bin/activate
pip install -r requirements.txt
python authorize_ads.py    # browser on 5by5; writes ads_token.json + prints .env lines
```

5. Put into `.env`:

```bash
GOOGLE_ADS_DEVELOPER_TOKEN=...
GOOGLE_ADS_CUSTOMER_ID=1234567890
# GOOGLE_ADS_LOGIN_CUSTOMER_ID=...   # if using MCC
GOOGLE_ADS_CLIENT_ID=...
GOOGLE_ADS_CLIENT_SECRET=...
GOOGLE_ADS_REFRESH_TOKEN=...
GOOGLE_ADS_GEO_TARGET_IDS=2840       # United States
USE_KEYWORD_PLANNER=1
```

6. Re-run `./run.sh --no-cooldown` — the Markdown will include volume/competition tables.

Seeds are taken from real GSC queries (opportunities + per-page queries).

---

## 3) Bing Webmaster (free complementary — enabled by default)

**Cost:** free (no API fees).

**Is Bing useful?** Yes, as a **secondary** lens—not a replacement for Google.

| Bing can add | Why it matters |
|--------------|----------------|
| **Different queries** | People phrase things differently on Bing; unique long-tails |
| **Different rankings** | A page weak on Google may already rank on Bing |
| **Smaller volume** | Usually much less traffic than Google in the US |

**Setup (once):**

1. Open [Bing Webmaster Tools](https://www.bing.com/webmasters) and verify `eagertobehealthy.com`
2. Gear → **API Access** → generate / copy API key
3. On 5by5:

```bash
cd ~/projects/seo-advisor && source .venv/bin/activate
python setup_bing.py YOUR_API_KEY
# optional: python setup_bing.py YOUR_API_KEY https://www.eagertobehealthy.com/
./run.sh --no-cooldown
```

That writes `BING_API_KEY` + `BING_SITE_URL` into `.env` and tests the connection.
`USE_BING=1` is the default.

---

## What each source is for (Claude)

| Source | Best for |
|--------|----------|
| **GSC** | What you already almost rank for; CTR/position fixes; cannibalization |
| **Keyword Planner** | Which of those terms (and related ideas) have real search volume / competition |
| **Bing** | Extra query ideas + pages that work on Microsoft search |
| **Claude (manual)** | Strategy: primary/supporting keywords, titles, meta, content actions |

---

## OAuth notes

| Auth | Command | Output |
|------|---------|--------|
| GSC | `python authorize.py` (RDP) | `token.json` |
| Ads | `python authorize_ads.py` (RDP) | `ads_token.json` + env vars |

Use project **`.venv`**, not `~/venv`.

Token files and `.env` are written with mode **0600**. All paths (`token.json`,
`client_secret.json`, `seo_state.db`, `reports/`) resolve against the project
directory, so the job works from any cwd (cron, systemd, promoted copy).

---

## CLI

```bash
./run.sh --no-cooldown
./run.sh --limit 10 --no-cooldown
./run.sh --with-local-llm    # optional Ollama pass
./run.sh --demo --limit 3
```
