"""R3: the PageSpeed header says how far a 429-stopped scan actually got."""
from __future__ import annotations

import briefing
import pagespeed


def header_lines(psi):
    payload = briefing.build_briefing_payload([], site="https://example.com/", pagespeed=psi)
    md = briefing.briefing_to_markdown(payload)
    return [line for line in md.splitlines() if line.startswith("**PageSpeed")]


def test_requested_vs_scanned_and_stop_note(monkeypatch):
    monkeypatch.setattr(pagespeed.config, "USE_PAGESPEED", True, raising=False)
    monkeypatch.setattr(pagespeed.config, "PAGESPEED_API_KEY", "k", raising=False)
    monkeypatch.setattr(pagespeed.config, "PAGESPEED_PAUSE_SECONDS", 0, raising=False)
    monkeypatch.setattr(
        pagespeed, "analyze_url",
        lambda url: {"url": url, "ok": False, "strategies": {},
                     "error": "mobile: HTTP 429 — rate limited", "rate_limited": True},
    )
    psi = pagespeed.scan_selected_urls([f"https://example.com/p{i}/" for i in range(5)])

    lines = header_lines(psi)

    assert "(ok 0/1 scanned of 5 requested)" in lines[0]
    assert any(
        line.startswith("**PageSpeed note:** Stopped after 1 of 5") for line in lines
    )


def test_complete_scan_has_no_requested_suffix_or_note():
    lines = header_lines({"enabled": True, "status": "enabled (API key set)",
                          "requested": 3, "scanned": 3, "ok_count": 3,
                          "stopped_early": False, "pages": {}, "notes": []})
    assert "(ok 3/3 scanned)" in lines[0]
    assert len(lines) == 1
