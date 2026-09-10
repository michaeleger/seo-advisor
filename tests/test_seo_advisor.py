"""
Local-LLM JSON salvage.

This code only runs when a local model returns malformed output, which is
precisely when you least want to be debugging it live. It is pure and cheap
to test, so it should be.
"""
from __future__ import annotations

import json

import pytest

import seo_advisor as sa


class TestExtractJson:
    def test_clean_json(self):
        assert sa._extract_json('{"primary_keyword": "kale"}') == {
            "primary_keyword": "kale"
        }

    def test_fenced_json_block(self):
        raw = '```json\n{"primary_keyword": "kale"}\n```'
        assert sa._extract_json(raw)["primary_keyword"] == "kale"

    def test_bare_fence_without_language(self):
        raw = '```\n{"primary_keyword": "kale"}\n```'
        assert sa._extract_json(raw)["primary_keyword"] == "kale"

    def test_trailing_comma_is_repaired(self):
        raw = '{"a": 1, "b": [1, 2,],}'
        assert sa._extract_json(raw) == {"a": 1, "b": [1, 2]}

    def test_smart_quotes_are_normalized(self):
        raw = '{“primary_keyword”: “kale”}'
        assert sa._extract_json(raw)["primary_keyword"] == "kale"

    def test_json_surrounded_by_prose(self):
        raw = 'Sure! Here you go:\n{"primary_keyword": "kale"}\nHope that helps.'
        assert sa._extract_json(raw)["primary_keyword"] == "kale"

    def test_empty_input_raises(self):
        with pytest.raises(json.JSONDecodeError):
            sa._extract_json("")

    def test_unsalvageable_input_raises(self):
        with pytest.raises(json.JSONDecodeError):
            sa._extract_json("no json here at all")


class TestNormalizeAnalysis:
    def test_fills_defaults_and_keeps_keywords(self):
        out = sa._normalize_analysis(
            {
                "primary_keyword": "kale benefits",
                "target_keywords": [
                    {"keyword": "kale", "rationale": "r", "intent": "Informational"}
                ],
                "notes": "underperforms on CTR",
            }
        )
        assert out["primary_keyword"] == "kale benefits"
        assert out["target_keywords"][0]["intent"] == "informational"
        assert out["target_keywords"][0]["priority"] == "medium"
        assert out["summary"] == "underperforms on CTR"

    def test_drops_malformed_keyword_entries(self):
        out = sa._normalize_analysis(
            {
                "target_keywords": [
                    {"keyword": "good"},
                    {"rationale": "no keyword field"},
                    "not a dict",
                    {"keyword": ""},
                ]
            }
        )
        assert [k["keyword"] for k in out["target_keywords"]] == ["good"]

    def test_primary_falls_back_to_first_keyword(self):
        out = sa._normalize_analysis({"target_keywords": [{"keyword": "kale"}]})
        assert out["primary_keyword"] == "kale"

    def test_survives_a_completely_empty_payload(self):
        out = sa._normalize_analysis({})
        assert out["primary_keyword"] == ""
        assert out["target_keywords"] == []
