# Install RankMath score exposure (free — no Claude audit)

RankMath **already** stores `rank_math_seo_score` on each post.  
SEO Advisor only needs that number exposed over REST so we **don’t** pay ~$1 for an AI “Audit SEO” each run.

## Easiest: upload zip (regular plugin)

**File on 5by5:**

```text
~/projects/seo-advisor/wordpress-plugin/eager-rankmath-rest.zip
```

1. Download/copy that zip to your computer (or upload from the server).
2. WordPress Admin → **Plugins → Add New → Upload Plugin**
3. Choose `eager-rankmath-rest.zip` → **Install Now** → **Activate**
4. Verify:

```text
https://www.eagertobehealthy.com/wp-json/etbh-seo/v1/rankmath-scores?per_page=5
```

You should see JSON with `"seo_score": 45` (numbers), not empty.

5. On 5by5:

```bash
cd ~/projects/seo-advisor && source .venv/bin/activate
python -c "import wp_client; s=wp_client.fetch_rankmath_scores(20); print(len(s), 'posts', sum(1 for v in s.values() if v.get('seo_score') is not None), 'scored'); print(list(s.values())[:3])"
./run.sh --no-cooldown
```

## Alternatives

| Method | Path |
|--------|------|
| **Zip upload (recommended)** | `eager-rankmath-rest.zip` via Plugins → Upload |
| Manual regular plugin | `wp-content/plugins/eager-rankmath-rest/eager-rankmath-rest.php` → Activate |
| mu-plugin (always on) | `wp-content/mu-plugins/eager-rankmath-rest.php` |

## Why not RankMath’s own `/links/posts`?

Editors often get **403**. Our endpoint reads the **same meta RankMath already wrote**, with no extra AI cost.

## Cost comparison

| Approach | Cost |
|----------|------|
| RankMath stored score via this plugin | **$0** |
| Claude / Post Studio Audit SEO | ~**$1**/report |
