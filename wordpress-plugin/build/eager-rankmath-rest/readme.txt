=== Eager RankMath REST Expose ===
Contributors: eagertobehealthy
Requires at least: 5.8
Tested up to: 6.7
Stable tag: 1.1.1

Exposes Rank Math's real rank_math_seo_score (and focus keyword / meta) via REST
so SEO Advisor can prioritize improvable posts without a paid Claude SEO audit.

== Installation ==
1. WP Admin → Plugins → Add New → Upload Plugin
2. Choose eager-rankmath-rest.zip → Install Now → Activate
3. Open: /wp-json/etbh-seo/v1/rankmath-scores?per_page=5

== Description ==
Reads meta RankMath already stores. Does not call AI.
