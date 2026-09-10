"""
HTML report rendering.

Each test here corresponds to a defect found by probing the renderer with
degenerate input, so they are regression guards rather than descriptions.
"""
from __future__ import annotations

import os
import tempfile

import report
import wp_client


def make_post(url="https://example.com/p/", title="A Post", rankmath=None):
    return {
        "id": 1, "title": title, "url": url, "content_plain": "",
        "content": wp_client.content_structure("<p>x</p>"),
        "rankmath": rankmath if rankmath is not None else {},
    }


def make_result(**over):
    base = {
        "metrics": {"page": "https://example.com/p/", "clicks": 1, "impressions": 10,
                    "ctr": 0.01, "position": 5.0, "reasons": ["Low CTR"]},
        "post": make_post(), "analysis": None, "queries": [],
        "prev_metrics": None, "pagespeed": None,
    }
    base.update(over)
    return base


def render(results):
    path = os.path.join(tempfile.mkdtemp(), "r.html")
    report.build_report(results, output_path=path)
    with open(path, encoding="utf-8") as fh:
        return fh.read()


class TestEscaping:
    def test_script_tag_in_title_is_escaped(self):
        out = render([make_result(post=make_post(title="<script>alert(1)</script>"))])
        assert "<script>alert(1)</script>" not in out
        assert "&lt;script&gt;" in out

    def test_angle_bracket_in_an_ordinary_title_does_not_break_markup(self):
        """The realistic case: a title like 'Fasting < 16 hours'."""
        out = render([make_result(post=make_post(title="Fasting < 16 hours & you"))])
        assert "Fasting &lt; 16 hours &amp; you" in out

    def test_rankmath_meta_from_wordpress_is_escaped(self):
        out = render([make_result(post=make_post(rankmath={
            "seo_score": 40,
            "focus_keyword": "<img src=x onerror=alert(1)>",
            "meta_title": "", "meta_description": "",
        }))])
        assert "onerror=alert(1)" not in out or "&lt;img" in out
        assert "<img src=x" not in out

    def test_model_supplied_keyword_text_is_escaped(self):
        out = render([make_result(analysis={
            "summary": "s",
            "target_keywords": [{"keyword": "<b>kw</b>", "rationale": "<i>r</i>",
                                 "intent": "informational", "priority": "high"}],
        })])
        assert "<b>kw</b>" not in out
        assert "<i>r</i>" not in out

    def test_url_is_escaped_in_href(self):
        out = render([make_result(post=make_post(url='https://e.com/"><script>x</script>'))])
        assert '"><script>' not in out


class TestRankMathZeroScore:
    def test_score_of_zero_still_renders_the_panel(self):
        """0 is falsy but is the worst possible score — the whole point."""
        out = render([make_result(post=make_post(rankmath={
            "seo_score": 0, "focus_keyword": "", "meta_title": "",
            "meta_description": "",
        }))])
        assert "RankMath Snapshot" in out
        assert "0/100" in out

    def test_genuinely_empty_rankmath_renders_no_panel(self):
        out = render([make_result(post=make_post(rankmath={
            "seo_score": None, "focus_keyword": "", "meta_title": "",
            "meta_description": "",
        }))])
        assert "RankMath Snapshot" not in out

    def test_has_value_helper(self):
        assert report._has_value({"seo_score": 0})
        assert report._has_value({"focus_keyword": "kale"})
        assert not report._has_value({})
        assert not report._has_value(None)
        assert not report._has_value({"seo_score": None, "focus_keyword": ""})


class TestPreviousMetrics:
    def test_partial_prev_metrics_does_not_crash(self):
        """
        save_page_state stores whatever metrics dict it was handed, and the
        stored shape has already changed once. A later run must not die
        rendering an older row — the crash would land after all the API work.
        """
        assert render([make_result(prev_metrics={"clicks": 1})])

    def test_empty_prev_metrics_does_not_crash(self):
        assert render([make_result(prev_metrics={})])

    def test_full_prev_metrics_renders_deltas(self):
        out = render([make_result(prev_metrics={
            "clicks": 5, "impressions": 100, "ctr": 0.05, "position": 10.0})])
        assert "pill-delta" in out


class TestDegenerateInput:
    def test_no_results(self):
        assert render([])

    def test_post_with_empty_url(self):
        assert render([make_result(post=make_post(url=""))])

    def test_pagespeed_failure_is_reported_not_raised(self):
        out = render([make_result(pagespeed={"ok": False, "error": "HTTP 429"})])
        assert "429" in out

    def test_pagespeed_with_all_null_scores(self):
        assert render([make_result(pagespeed={"ok": True, "strategies": {"mobile": {
            "scores": {"performance": None, "accessibility": None,
                       "best_practices": None, "seo": None},
            "lab": {"core_metrics": {}, "html_relevant_issues": []}}}})])

    def test_queries_with_null_numerics(self):
        assert render([make_result(queries=[{"query": "q", "clicks": None,
            "impressions": None, "ctr": None, "position": None}])])
