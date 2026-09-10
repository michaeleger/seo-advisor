"""
Report rendering.

Mostly smoke tests. briefing_to_markdown is `.get()`-heavy defensive code that
runs against whatever survived a partly-failed harvest — a page with no
WordPress match, no queries, no PageSpeed. These tests protect the
defensiveness rather than the wording, so they should not need touching every
time the prompt is reworded.

The exceptions are the two things that are decisions rather than phrasing:
diagnostics must not be framed as targets, and article text must not be
shipped in the report.
"""
from __future__ import annotations

import briefing
import wp_client


def make_post(url, *, html="", title="A Post", score=None, focus=""):
    return {
        "id": 1,
        "title": title,
        "url": url,
        "content_plain": "",
        "content": wp_client.content_structure(html),
        "rankmath": {"seo_score": score, "focus_keyword": focus},
    }


def make_result(post, **over):
    base = {
        "metrics": {
            "page": post["url"], "clicks": 2, "impressions": 400, "ctr": 0.005,
            "position": 18.0, "reasons": ["Low CTR"],
        },
        "post": post, "analysis": None, "queries": [], "period_comparison": {},
        "devices": [], "countries": [], "monthly_trend": [], "prev_metrics": None,
        "pagespeed": None,
    }
    base.update(over)
    return base


def render(results):
    return briefing.briefing_to_markdown(
        briefing.build_briefing_payload(results, site="https://example.com/")
    )


class TestSmoke:
    def test_renders_with_no_pages_at_all(self):
        assert render([])

    def test_renders_a_page_with_no_enrichment(self):
        post = make_post("https://example.com/p/", html="<h1>T</h1><p>hi</p>")
        assert "https://example.com/p/" in render([make_result(post)])

    def test_renders_a_stub_page_with_no_wordpress_match(self):
        """Partly-failed harvest: WordPress lookup missed."""
        stub = {
            "id": None, "title": "Gone", "url": "https://example.com/gone/",
            "content_plain": "", "content": wp_client.content_structure(""),
            "rankmath": {},
        }
        out = render([make_result(stub)])
        assert "not retrieved from WordPress" in out

    def test_renders_when_optional_keys_are_missing_entirely(self):
        post = make_post("https://example.com/p/", html="<p>hi</p>")
        thin = {"metrics": {"page": post["url"], "clicks": 0, "impressions": 0,
                            "ctr": 0.0, "position": 0.0}, "post": post}
        assert render([thin])

    def test_json_payload_is_serializable(self):
        post = make_post("https://example.com/p/", html="<h1>T</h1><p>hi</p>")
        payload = briefing.build_briefing_payload(
            [make_result(post)], site="https://example.com/"
        )
        assert briefing.briefing_to_json(payload)


class TestContentStaysOutOfTheReport:
    def test_article_text_is_not_shipped(self):
        """The live page is the source of truth; the report carries measurements."""
        marker = "distinctivephrase"
        post = make_post(
            "https://example.com/p/", html=f"<h1>T</h1><p>{marker} " + "word " * 400 + "</p>"
        )
        out = render([make_result(post)])
        assert marker not in out
        assert "401 words" in out or "words" in out

    def test_heading_outline_is_included(self):
        post = make_post(
            "https://example.com/p/",
            html="<h1>Title</h1><h2>Section</h2><h3>Sub</h3><p>x</p>",
        )
        out = render([make_result(post)])
        for text in ("H1 · Title", "H2 · Section", "H3 · Sub"):
            assert text in out


class TestDiagnosticsAreNotTargets:
    def test_rubric_line_is_framed_as_observation(self):
        post = make_post("https://example.com/p/", html="<p>too short</p>")
        out = render([make_result(post)])
        assert "observations, not targets" in out

    def test_prompt_forbids_padding_and_checklist_filler(self):
        prompt = briefing.CLAUDE_HANDOFF_PROMPT
        assert "Do not pad to reach a word count." in prompt
        assert "NOT A SPECIFICATION" in prompt

    def test_prompt_tells_the_model_to_stop_if_it_cannot_read_a_page(self):
        assert "IF YOU CANNOT OPEN A PAGE" in briefing.CLAUDE_HANDOFF_PROMPT

    def test_rubric_reports_measurement_before_threshold(self):
        """'102 words (Rank Math wants >=600)', not 'under 600 words'."""
        post = make_post("https://example.com/p/", html="<p>" + "w " * 50 + "</p>")
        out = render([make_result(post)])
        assert "Rank Math wants" in out


class TestSnapshotReference:
    def test_snapshot_path_is_surfaced_when_present(self):
        post = make_post("https://example.com/p/", html="<p>hi</p>")
        result = make_result(post, snapshot_path="reports/pages_2026-01-01/p.html")
        assert "reports/pages_2026-01-01/p.html" in render([result])

    def test_no_per_page_snapshot_bullet_when_absent(self):
        # "Local snapshot" also appears in the static how-to-use text, so
        # assert on the per-page bullet specifically.
        post = make_post("https://example.com/p/", html="<p>hi</p>")
        assert "- **Local snapshot" not in render([make_result(post)])
