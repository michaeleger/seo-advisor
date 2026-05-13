# SEO Advisor — Setup Guide

## Quick start

```bash
pip install -r requirements.txt
cp .env.example .env
# Complete the Google Search Console steps below, then:
python main.py
# Open the generated seo_report_YYYY-MM-DD.html in your browser
```

---

## Step 1 — Connect Google Search Console

### 1a. Create a Google Cloud project

1. Go to https://console.cloud.google.com
2. Click **Select a project → New Project**. Name it anything (e.g. "SEO Advisor").
3. Click **Create**.

### 1b. Enable the Search Console API

1. In your new project, go to **APIs & Services → Library**
2. Search for **"Google Search Console API"**
3. Click it → **Enable**

### 1c. Create a Service Account

1. Go to **APIs & Services → Credentials → Create Credentials → Service Account**
2. Give it a name (e.g. "seo-advisor")
3. Click **Create and Continue** → skip the optional role fields → **Done**
4. Click the service account you just created
5. Go to the **Keys** tab → **Add Key → Create new key → JSON**
6. A `credentials.json` file will download — put it in this project folder
7. Note the service account's **email address** (looks like `seo-advisor@your-project.iam.gserviceaccount.com`)

### 1d. Grant the service account access to your Search Console property

1. Go to https://search.google.com/search-console
2. Select your property (eagertobehealthy.com)
3. Click **Settings → Users and permissions → Add user**
4. Enter the service account email from step 1c
5. Set permission to **Restricted** (read-only is enough)
6. Click **Add**

### 1e. Set the site URL in `.env`

Check your Search Console property URL exactly — it may be:
- `https://eagertobehealthy.com/` (with trailing slash)
- `sc-domain:eagertobehealthy.com` (domain property)

Copy it exactly into `GSC_SITE_URL` in your `.env` file.

---

## Step 2 — Anthropic API key

1. Go to https://console.anthropic.com → API Keys → Create Key
2. Copy it into `ANTHROPIC_API_KEY` in `.env`

---

## Tuning what counts as "low performing"

Edit these values in `.env`:

| Variable | Default | What it does |
|---|---|---|
| `DATE_RANGE_DAYS` | 90 | Days of GSC data to analyze |
| `MIN_IMPRESSIONS` | 50 | Posts with fewer impressions are skipped (too little data) |
| `MAX_CTR` | 0.05 | Posts below this CTR (5%) are flagged |
| `MAX_POSITION` | 20 | Posts ranked worse than position 20 are flagged |
| `MAX_POSTS_TO_ANALYZE` | 15 | Cap on Claude API calls per run |

**Start broad, then tighten:** if you get too many results, raise `MIN_IMPRESSIONS`
or lower `MAX_POSITION`. If you get none, lower `MIN_IMPRESSIONS`.

---

## Reading the report

Each post card shows:
- **Red badges** — the specific reasons it was flagged
- **Summary** — Claude's diagnosis of the core problem
- **Target Keywords** — keywords to optimize toward, with rationale
- **Suggested Titles** — CTR-optimized title rewrites
- **Phrases to Add** — exact phrases and where to put them
- **Content Recommendations** — structural changes (new sections, FAQ, meta description, etc.)

Posts are ordered by impression volume — tackle the top ones first for maximum impact.

---

## Running on a schedule

To generate a fresh report weekly, add a cron job:

```bash
crontab -e
# Add:
0 8 * * 1 cd /path/to/seo-advisor && python main.py >> seo_advisor.log 2>&1
```

This runs every Monday at 8am and saves a dated HTML file each time.
