"""
SEO Advisor — scans eagertobehealthy.com for low-performing posts
and produces a Claude-powered HTML report with keyword, title, and
content recommendations.
"""
import logging
import os
import sys
from datetime import date

import analyzer
import config
import db
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
    no_cooldown = "--no-cooldown" in sys.argv

    db.init_db()
    os.makedirs(config.REPORTS_DIR, exist_ok=True)

    log.info("Fetching GSC page metrics for %s …", config.GSC_SITE_URL)
    page_metrics = gsc.get_page_metrics()
    log.info("  %d pages found in Search Console.", len(page_metrics))

    if no_cooldown:
        excluded: set[str] = set()
        log.info("  Cooldown disabled (--no-cooldown).")
    else:
        excluded = db.cooldown_urls(page_metrics, config.COOLDOWN_DAYS)
        log.info("  %d page(s) skipped (within %d-day cooldown).", len(excluded), config.COOLDOWN_DAYS)

    log.info("Identifying worst-performing posts …")
    low_performers = analyzer.identify_low_performers(page_metrics, excluded_urls=excluded)

    if not low_performers:
        log.info(
            "No eligible low-performing posts found. "
            "All candidates may be in cooldown, or try adjusting thresholds in .env."
        )
        sys.exit(0)

    log.info("Found %d post(s) to analyze (cap: %d).", len(low_performers), config.MAX_POSTS_TO_ANALYZE)

    output_file = os.path.join(
        config.REPORTS_DIR, f"seo_report_{date.today().isoformat()}.html"
    )

    results = []
    for i, metrics in enumerate(low_performers, 1):
        url = metrics["page"]
        log.info("[%d/%d] %s", i, len(low_performers), url)

        try:
            post = wp_client.get_post_content(url)
            if not post:
                log.warning("  Could not fetch post content — skipping.")
                continue

            log.info("  Title: %s", post["title"])

            log.info("  Fetching top queries …")
            queries = gsc.get_page_queries(url)
            log.info("  %d queries found.", len(queries))

            prev_state = db.get_page_state(url)
            prev_metrics = prev_state["last_metrics"] if prev_state else None
            if prev_metrics:
                log.info("  Previous analysis: %s (delta will be shown).", prev_state["last_analyzed"])

            log.info("  Running SEO analysis …")
            analysis = seo_advisor.analyze_post(metrics, queries, post)
            if analysis:
                log.info("  ✓ Analysis complete.")
            else:
                log.warning("  ✗ Analysis failed — post will appear in report without AI suggestions.")

            results.append({
                "metrics": metrics,
                "post": post,
                "analysis": analysis,
                "prev_metrics": prev_metrics,
            })
            db.save_page_state(url, metrics, output_file)

        except RuntimeError:
            # Re-raise config errors (e.g. missing API key) — no point continuing.
            raise
        except Exception as exc:
            log.error("  Unexpected error processing %s: %s — skipping post.", url, exc)

    if not results:
        log.error("No results to report. Check that your WordPress posts are accessible.")
        sys.exit(1)

    log.info("Building HTML report …")
    path = report.build_report(results, output_path=output_file)
    log.info("Done! Report saved to: %s", path)


if __name__ == "__main__":
    main()
