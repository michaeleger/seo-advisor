# SEO Advisor — how a run ranks pages

Install, OAuth, Bing, PageSpeed, Keyword Planner, the local LLM, scheduling, and tests are in [README.md](README.md). The commands below assume you already did this from a clone, in whatever directory you cloned into:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env && chmod 600 .env
```

Edit `.env` and replace `example.com` with your site. `GSC_SITE_URL`, `WP_SITE_URL`, and `BING_SITE_URL` have no default domain. Then:

```bash
./run.sh --help
./run.sh --demo --limit 3
```

`./run.sh` expects `.venv` next to itself. It `cd`s to the project directory, so the shell's current directory does not matter.

## Pipeline

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
 YOU paste into a chat model → keywords + fresh HTML guidance
```

The pipeline does not write to WordPress.

## How pages are ranked (neglected under-performance)

```
priority = missed clicks × neglect × fixability × decay
```

| Factor | What it measures | Knobs |
| --- | --- | --- |
| **missed clicks** | GSC demand the page fails to capture: clicks lost to a weak CTR for its position, plus clicks available by ranking at `TARGET_POSITION`. Sized over `DATE_RANGE_DAYS` (reported as `clicks/yr` at 365, `clicks/<N>d` otherwise). | `DATE_RANGE_DAYS`, `TARGET_POSITION` |
| **neglect** | 1.0 for a page edited today, rising to `NEGLECT_MAX_MULTIPLIER` after `NEGLECT_FULL_DAYS` untouched. Unknown edit date = 1.0. | `NEGLECT_FULL_DAYS`, `NEGLECT_MAX_MULTIPLIER` |
| **fixability** | Modest multiplier from the Rank Math score: 1.0 (score 100) → 2.0 (score 0); unknown = 1.3. | — |
| **decay** | Up to 1.5× when impressions fall versus the prior adjacent window. | `DECAY_WINDOW_DAYS` |

Gates before ranking: pages under `MIN_IMPRESSIONS` are skipped (undiscovered, not under-performing — unless `INCLUDE_ZERO_TRAFFIC_PAGES=1`); pages at or above `RANKMATH_SKIP_SCORE` (default 80) are skipped; `SKIP_*` filters drop site furniture.

**Rank Math is not the sort key.** It measures SEO-form completeness, so a bio or booking page scores ~9 forever and would otherwise top every run.

**Backoff:** a page suggested but not edited is deferred (`BACKOFF_DAYS`, default `30,60,90,180`, last value is a cap) and always comes back. `./run.sh --no-cooldown` ignores that deferral for one run. A detected edit holds the page for `EDIT_COOLDOWN_DAYS` (default 90) so the search engine can reprocess it.

**Catalog budgets:** `WP_CATALOG_PER_TYPE_MAX` (default 2000) applies to posts and pages separately; `WP_RANKMATH_MAX_ITEMS` (default 2000) caps the score overlay. Truncation is logged. See `.env.example` for every knob and its default.

The score used is the **real Rank Math plugin score** (`rank_math_seo_score`), **not** an LLM "Audit SEO" estimate.

## WordPress and Rank Math

Public `wp/v2` post JSON does not include `rank_math_seo_score` unless something exposes it. Two options. They are the same two options as in the README.

### Option A — Application Password and Rank Math's own API

1. WordPress Admin → Users → your user → **Application Passwords** → create one.
2. In `.env`:

```bash
WP_APP_USER=your_wp_username
WP_APP_PASSWORD=xxxx xxxx xxxx xxxx xxxx xxxx
```

3. The advisor calls `GET /wp-json/rankmath/v1/links/posts` with `seo_score_range=bad|good|great|no-score`.

Rank Math often returns **403** on that route for Editor accounts. Use a user Rank Math allows (typically an Administrator). If you get 403, use option B. The Application Password is also sent on ordinary WordPress REST reads when both variables are set.

### Option B — the included plugin

Install `wordpress-plugin/eager-rankmath-rest.php`. [wordpress-plugin/INSTALL.md](wordpress-plugin/INSTALL.md) has the zip upload, a normal plugin path, and the mu-plugin path.

The plugin registers:

```text
GET /wp-json/etbh-seo/v1/rankmath-scores
```

**That endpoint is public by design.** `permission_callback` is `__return_true`, so Rank Math scores for published posts and pages are world-readable. The plugin also registers the score, focus keyword, SEO title, and meta description with a public auth callback on posts and pages, so those fields show up on ordinary `wp/v2` responses too. Install it only if that is acceptable. Do not expect the advisor to lock the route down; the plugin ships this way on purpose, and this repo does not change it.

No Application Password is required to read scores through option B.

### Which one the advisor calls

`wp_client.fetch_rankmath_scores` requests the plugin endpoint first. HTTP 404 (plugin not installed) falls through to option A when an Application Password is set. When the plugin returns rows, Rank Math's `/links/posts` route is not called.

Verify from this directory, venv active, after `WP_SITE_URL` is set:

```bash
python -c "import wp_client; ps=wp_client.list_content_with_rankmath(types=('posts',), per_type_max=5); print([(p['title'][:40], p['rankmath']) for p in ps])"
```

You want integer `seo_score` values.

## Other sources

Each of these is set up in [README.md](README.md). Short version:

| Source | What you set | Notes |
| --- | --- | --- |
| Search Console | `client_secret.json`, `python authorize.py`, `GSC_SITE_URL` | `--no-browser` plus an SSH tunnel (`-L 4567:localhost:4567`) when this host has no browser. GSC is your site's performance only. It does not include market search volume. |
| Keyword Planner | `python authorize_ads.py`, customer id, `USE_KEYWORD_PLANNER=1` | Needs Basic (or higher) Google Ads API access on the Cloud project. Headless: `--start`, tunnel port 4568, `--finish`. |
| Bing | `python setup_bing.py YOUR_API_KEY https://www.example.com/` | Free. Pass the verified site URL. Omitting it uses `WP_SITE_URL` and prints that. No built-in domain. |
| PageSpeed | `PAGESPEED_API_KEY` | Selected URLs only. Without a key the stage is skipped. |
| Local LLM | `./run.sh --with-local-llm` | Off by default. `--model` names the Ollama model. |

## CLI

```bash
./run.sh --help
./run.sh --demo --limit 3
./run.sh --limit 10
./run.sh --no-cooldown
./run.sh --with-local-llm --model llama3.1:8b
./run.sh -v
```
