# SEO Advisor

SEO Advisor is a local pipeline you run on demand, typically once a week, for a WordPress site that uses [Rank Math](https://rankmath.com/). It reads your search performance, ranks pages by neglected under-performance, and writes a Markdown report you paste into a chat model (Claude, Grok, or similar) for keyword and HTML guidance.

It does not write back to WordPress. The report is the handoff.

Data it can use:

| Source | Role | Required |
| --- | --- | --- |
| WordPress + Rank Math | Page list, edit dates, stored SEO scores | WordPress for every run, including `--demo`. Rank Math scores are optional for `--demo`. |
| [Google Search Console](https://search.google.com/search-console) | Clicks, impressions, CTR, position | A real run. Not used by `--demo`. |
| [Bing Webmaster Tools](https://www.bing.com/webmasters) | A second set of queries and pages | Optional. Free. |
| [PageSpeed Insights](https://developers.google.com/speed/docs/insights/v5/get-started) | Lighthouse lab data and CrUX field data, selected URLs only | Optional. Free API key. |
| [Google Ads Keyword Planner](https://ads.google.com/) | Search volume and competition | Optional, and gated on Ads API access. |
| Local LLM (Ollama, or any OpenAI-compatible server) | A keyword pass before you paste the report | Optional. Off unless you ask. |

How a page gets to the top of the report: missed clicks (Search Console) × neglect (time since the last edit) × fixability (Rank Math score) × decay (impressions versus the prior window). The ranking knobs are documented in [SETUP.md](SETUP.md) and [`.env.example`](.env.example).

Copyright (C) 2026 Michael Eger. Licensed under the GNU GPL v3.0 — see [License](#license).

## Requirements

- Python 3.10 or newer (`python3 --version`)
- A WordPress site whose REST API can list published posts (`/wp-json/wp/v2/posts`)
- For a real run: a Google account with access to that site's Search Console property
- Network access to the APIs you turn on

`--demo` does not need Google. It does need `WP_SITE_URL` pointing at a WordPress site.

## Install

```bash
git clone https://github.com/michaeleger/seo-advisor.git
cd seo-advisor
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
chmod 600 .env                     # Unix. Keeps tokens in .env owner-only.
```

Edit `.env` and replace every `example.com` with your site before you run. `config.py` does not fill in a domain for you. Copying the example and leaving the placeholders makes `--demo` request `example.com`.

`.env`, `token.json`, `ads_token.json`, `client_secret.json`, and `seo_state.db` are gitignored. Do not commit them.

`./run.sh` changes to this directory and runs `python main.py` inside `.venv`. Create the virtualenv before the first `./run.sh`. On Windows, use `python main.py` with the venv activated instead of `./run.sh`.

## First run (`--demo`)

Set `WP_SITE_URL` in `.env` to your WordPress origin, with no path:

```bash
WP_SITE_URL=https://www.example.com
```

The site must return published posts from `/wp-json/wp/v2/posts`. If that route is not public, also set `WP_APP_USER` and `WP_APP_PASSWORD` (an [Application Password](https://make.wordpress.org/core/2020/11/05/application-passwords-integration-guide/)).

```bash
source .venv/bin/activate
./run.sh --demo --limit 3
```

That writes `reports/seo_report_YYYY-MM-DD.md` (plus an HTML view and a JSON briefing) using live WordPress posts and synthetic Search Console numbers. It does not call Search Console, Bing, Keyword Planner, or PageSpeed. `reports/` is gitignored; the files contain your content.

## Search Console OAuth

1. In [Google Cloud Console](https://console.cloud.google.com/), select or create a project.
2. Enable **Google Search Console API**.
3. Configure the OAuth consent screen. While the app is in **Testing**, add the Google account that owns the Search Console property as a test user.
4. Create an OAuth client ID of type **Desktop app**. Download the JSON and save it in this directory as `client_secret.json` (gitignored).
5. In `.env`, set `GSC_SITE_URL` to the property exactly as Search Console shows it:
   - Domain property: `sc-domain:example.com`
   - URL-prefix property: `https://www.example.com/`

Authorize on a machine where a browser can reach this process:

```bash
source .venv/bin/activate
python authorize.py
```

Sign in with the Google account that can read the property. The script writes `token.json` (mode 0600).

Headless server, browser on your computer. The callback port defaults to **4567** (`--port`, or `GSC_OAUTH_PORT`):

```bash
ssh -L 4567:localhost:4567 user@your-server
# on the server, venv active:
python authorize.py --no-browser
```

Open the URL the script prints in the browser on the computer that owns the tunnel. `localhost` in that URL has to land on the server process.

## WordPress and Rank Math

The advisor reads Rank Math's stored score (`rank_math_seo_score`). That number is not an LLM "Audit SEO" opinion. A normal public `wp/v2` response does not include it. Two ways to supply it:

### Option A — Application Password and Rank Math's own API

1. WordPress Admin → Users → your user → **Application Passwords** → create one.
2. In `.env`:

```bash
WP_APP_USER=your_wp_username
WP_APP_PASSWORD=xxxx xxxx xxxx xxxx xxxx xxxx
```

The advisor then calls `GET /wp-json/rankmath/v1/links/posts`. Rank Math often returns **403** on that route for Editor accounts. Use a user Rank Math allows to call it (typically an Administrator). The same Application Password is also sent on ordinary WordPress REST reads, which matters when `/wp-json/` is not public.

### Option B — the plugin in this repo

Install `wordpress-plugin/eager-rankmath-rest.zip` (Plugins → Add New → Upload Plugin → Activate), or copy `wordpress-plugin/eager-rankmath-rest.php` into place. Paths and the check URL are in [wordpress-plugin/INSTALL.md](wordpress-plugin/INSTALL.md).

The plugin adds:

```text
GET /wp-json/etbh-seo/v1/rankmath-scores
```

**That endpoint is public by design.** Its permission check is `__return_true`, so anyone on the internet can read Rank Math scores for published posts and pages. The plugin also registers the score, focus keyword, SEO title, and meta description for public reads on the standard post and page REST responses. Install it only if that exposure is acceptable. This repo does not change that behavior.

No Application Password is required for the scores when the plugin is installed.

The advisor requests the plugin endpoint first. If it is not installed (HTTP 404), it uses option A when `WP_APP_USER` and `WP_APP_PASSWORD` are set.

Check either path from the project, with the venv active:

```bash
python -c "import wp_client; ps=wp_client.list_content_with_rankmath(types=('posts',), per_type_max=5); print([(p['title'][:40], p['rankmath']) for p in ps])"
```

You want integer `seo_score` values.

## PageSpeed (optional)

PageSpeed runs only on the pages a run already selected, not on the whole site.

1. Enable **PageSpeed Insights API** on the same or another Cloud project.
2. Create an API key. Restrict it to that API if you want.
3. In `.env`:

```bash
USE_PAGESPEED=1
PAGESPEED_API_KEY=your_key
PAGESPEED_STRATEGIES=mobile
# or: mobile,desktop
```

Without `PAGESPEED_API_KEY` the stage is skipped. Anonymous quota answers HTTP 429.

## Bing Webmaster (optional)

Free. Useful as a second query list, not as a replacement for Google.

1. Verify the site in [Bing Webmaster Tools](https://www.bing.com/webmasters).
2. Gear → **API Access** → create a key.
3. With the venv active, pass the key and the verified site URL. The URL has to match Bing, including `www` and a trailing slash when Bing shows them:

```bash
python setup_bing.py YOUR_API_KEY https://www.example.com/
```

If you omit the URL, the script uses `WP_SITE_URL` from `.env` and prints that choice. It will not invent a domain. It writes `BING_API_KEY` and `BING_SITE_URL` into `.env` and tests the connection.

`USE_BING` defaults to on. The stage still runs only when both the key and `BING_SITE_URL` are set.

## Google Ads Keyword Planner (optional)

Off until the Cloud project has **Basic** (or higher) Google Ads API access. As of the notes in this repo, that access level lives on the Cloud project's Google Ads API Overview. A developer token is accepted if you have one and is not required for the client to run.

1. Enable **Google Ads API** on the Cloud project (the same OAuth client as Search Console is fine).
2. Apply for Basic access and finish brand verification if Google asks.
3. Note the Ads customer ID (digits only). If you use a manager account, note that ID too.
4. Authorize. Default callback port is **4568**:

```bash
python authorize_ads.py
```

Headless two-step (the script keeps the PKCE verifier in `.ads_oauth_pending.json`, which is gitignored):

```bash
python authorize_ads.py --start
# ssh -L 4568:localhost:4568 user@your-server
# open the printed URL, then copy the full callback URL even if the browser says connection refused
python authorize_ads.py --finish 'http://localhost:4568/?code=...'
```

5. Put the remaining values in `.env` (the authorize script writes the OAuth client id, secret, and refresh token for you):

```bash
GOOGLE_ADS_CUSTOMER_ID=1234567890
# GOOGLE_ADS_LOGIN_CUSTOMER_ID=...   # manager account only
# GOOGLE_ADS_DEVELOPER_TOKEN=...     # optional
GOOGLE_ADS_GEO_TARGET_IDS=2840       # United States
USE_KEYWORD_PLANNER=1
```

Seeds come from Search Console queries on the pages in the report.

## Local LLM (optional)

Default is off: the Markdown report is the thing you paste into a chat model. To run a local keyword pass first, install [Ollama](https://ollama.com/) (the default is `http://127.0.0.1:11434` and `llama3.1:8b`) and either set `USE_LOCAL_LLM=1` or pass `--with-local-llm`.

`OPENAI_COMPAT_BASE_URL`, `OPENAI_COMPAT_MODEL`, and `OPENAI_COMPAT_API_KEY` in `.env.example` point the same pass at another local server. Set `LOCAL_LLM_PROVIDER=openai_compat` for that.

## Running

```bash
./run.sh --help
./run.sh --demo --limit 3          # live WordPress, synthetic Search Console
./run.sh                           # real run, default 10 pages
./run.sh --limit 10                # how many pages to package
./run.sh --no-cooldown             # include pages still inside their backoff window
./run.sh --with-local-llm          # Ollama (or OpenAI-compatible) keyword pass
./run.sh --with-local-llm --model llama3.1:8b
./run.sh -v                        # debug logging
```

`--limit` overrides `MAX_POSTS_TO_ANALYZE` (default 10) for that process. `--no-cooldown` ignores each page's `defer_until` date. A page that was suggested and not edited otherwise waits out `BACKOFF_DAYS` (default `30,60,90,180`, and the last value is a cap) and then comes back. A detected edit holds the page for `EDIT_COOLDOWN_DAYS` (default 90). `--model` sets the Ollama model name; the local pass still runs only with `--with-local-llm` or `USE_LOCAL_LLM=1`.

A full run needs `token.json`, `GSC_SITE_URL`, and `WP_SITE_URL`. Outputs, all under `reports/` and gitignored:

- `seo_report_YYYY-MM-DD.md` — paste this into the chat model
- `seo_report_YYYY-MM-DD.html` — the same run in a browser
- `seo_briefing_YYYY-MM-DD.json` — machine-readable copy
- `pages_YYYY-MM-DD/` — WordPress HTML snapshots, when `SAVE_PAGE_SNAPSHOTS=1` (the default)

`nginx-seo-reports.conf` and `cowork-nginx-updated.conf` are notes from one host for serving `reports/` on loopback. They are not part of install. Reports hold Search Console numbers and copies of page HTML, so do not publish that directory.

Paths (`token.json`, `client_secret.json`, `seo_state.db`, `reports/`) resolve against this directory, so cron and systemd can start the job from any working directory.

## Scheduling

`./run.sh` activates `.venv` itself. Point the job at the script by absolute path.

Cron, Monday 06:15:

```cron
15 6 * * 1 /path/to/seo-advisor/run.sh >> /path/to/seo-advisor/seo-advisor.log 2>&1
```

systemd user units. `seo-advisor.service`:

```ini
[Service]
Type=oneshot
WorkingDirectory=/path/to/seo-advisor
ExecStart=/path/to/seo-advisor/run.sh
```

`seo-advisor.timer`:

```ini
[Unit]
Description=Weekly SEO Advisor run

[Timer]
OnCalendar=Mon *-*-* 06:15:00
Persistent=true

[Install]
WantedBy=timers.target
```

```bash
systemctl --user daemon-reload
systemctl --user enable --now seo-advisor.timer
```

`*.log` is gitignored.

## Tests

The suite does not call live APIs.

```bash
source .venv/bin/activate
pip install -r requirements-dev.txt
pytest
```

## License

GNU General Public License v3.0 only. The full text is [LICENSE](LICENSE). Nothing in this repo named AGPL, LGPL, or another GNU variant; GPL-3.0 matches the owner's intent to use a GNU license.

You can copy, modify, and share this program under those terms. There is no warranty.

## Feedback

Issues and pull requests on [github.com/michaeleger/seo-advisor](https://github.com/michaeleger/seo-advisor) are welcome. Michael Eger wants people to use this and to say what broke.
