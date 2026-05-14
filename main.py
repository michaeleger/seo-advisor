"""
SEO Advisor — scans eagertobehealthy.com for low-performing posts
and produces a Claude-powered HTML report with keyword, title, and
content recommendations.
"""
import logging
import sys
from datetime import date

import analyzer
import config
import gsc
import report
import seo_advisor
import wp_client

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


def main() -> None:
    log.info("Fetching GSC page metrics for %s …", config.GSC_SITE_URL)
    page_metrics = gsc.get_page_metrics()
    log.info("  %d pages found in Search Console.", len(page_metrics))

    log.info("Identifying low-performing posts …")
    low_performers = analyzer.identify_low_performers(page_metrics)

    if not low_performers:
        log.info("No low-performing posts found with current thresholds. "
                 "Try lowering MIN_IMPRESSIONS or raising MAX_CTR in .env")
        sys.exit(0)

    log.info("Found %d post(s) to analyze (cap: %d).", len(low_performers), config.MAX_POSTS_TO_ANALYZE)

    results = []
    for i, metrics in enumerate(low_performers, 1):
        url = metrics["page"]
        log.info("[%d/%d] %s", i, len(low_performers), url)

        # Fetch WordPress content
        post = wp_client.get_post_content(url)
        if not post:
            log.warning("  Could not fetch post content — skipping.")
            continue

        log.info("  Title: %s", post["title"])

        # Fetch per-page query data
        log.info("  Fetching top queries …")
        queries = gsc.get_page_queries(url)
        log.info("  %d queries found.", len(queries))

        # Run Claude SEO analysis
        log.info("  Running SEO analysis …")
        analysis = seo_advisor.analyze_post(metrics, queries, post)
        if analysis:
            log.info("  ✓ Analysis complete.")
        else:
            log.warning("  ✗ Analysis failed.")

        results.append({"metrics": metrics, "post": post, "analysis": analysis})

    if not results:
        log.error("No results to report. Check that your WordPress posts are accessible.")
        sys.exit(1)

    output_file = f"seo_report_{date.today().isoformat()}.html"
    log.info("Building HTML report …")
    path = report.build_report(results, output_path=output_file)
    log.info("Done! Report saved to: %s", path)
    log.info("Open it in your browser: file://%s/%s", __import__('os').getcwd(), path)


if __name__ == "__main__":
    main()
