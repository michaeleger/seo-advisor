# Rank Math scores for SEO Advisor

SEO Advisor wants Rank Math's stored score (`rank_math_seo_score`) so it can rank pages without paying a chat model to invent one. Rank Math's own route, `GET /wp-json/rankmath/v1/links/posts`, often returns **403** for Editor accounts. This plugin reads the meta Rank Math already saved.

This is option B from [the README](../README.md#wordpress-and-rank-math). Option A is an Application Password plus that Rank Math route, with no plugin.

## The endpoint is public

Installing this plugin makes Rank Math scores world-readable.

`GET /wp-json/etbh-seo/v1/rankmath-scores` is registered with `permission_callback` set to `__return_true`. Anyone who can reach the site can read scores for published posts and pages. No cookie and no Application Password is required.

The same file registers `rank_math_seo_score`, `rank_math_focus_keyword`, `rank_math_title`, and `rank_math_description` with a public auth callback, and adds a `rankmath` field on public `wp/v2` post and page responses. Those fields become world-readable too.

That is intentional. The advisor does not change it. If scores, focus keywords, or SEO titles must stay private, do not install this plugin — use option A instead.

## Install

The files in this repo:

- `wordpress-plugin/eager-rankmath-rest.zip` — upload from wp-admin
- `wordpress-plugin/eager-rankmath-rest.php` — copy onto the server

| Method | Where it goes |
| --- | --- |
| Zip upload | Plugins → Add New → Upload Plugin → choose `eager-rankmath-rest.zip` → Install Now → **Activate** |
| Regular plugin | `wp-content/plugins/eager-rankmath-rest/eager-rankmath-rest.php`, then **Activate** |
| Must-use plugin (always on, no Activate button) | `wp-content/mu-plugins/eager-rankmath-rest.php` |

## Check

Open this in a browser where you are **not** logged in to WordPress. A login wall would mean you are not looking at the public route:

```text
https://YOUR-SITE/wp-json/etbh-seo/v1/rankmath-scores?per_page=5
```

You should see JSON with numeric `seo_score` values. Seeing them without logging in is the public read described above.

From a clone of this repo, with `.venv` active and `WP_SITE_URL` set in `.env`:

```bash
python -c "import wp_client; s=wp_client.fetch_rankmath_scores(20); print(len(s), 'posts', sum(1 for v in s.values() if v.get('seo_score') is not None), 'scored')"
./run.sh --no-cooldown
```

The advisor calls this endpoint first. When it returns rows, Rank Math's `/links/posts` route is not used.

## What it costs

| Approach | Who can read the scores | Cost |
| --- | --- | --- |
| Option A: Application Password + `/wp-json/rankmath/v1/links/posts` | The WordPress user you authenticate, if Rank Math allows that user | $0 |
| Option B: this plugin, `/wp-json/etbh-seo/v1/rankmath-scores` | Anyone | $0 |
| A chat model's "Audit SEO" | Not a Rank Math score | Whatever that chat costs, and the advisor does not use it as the score |
