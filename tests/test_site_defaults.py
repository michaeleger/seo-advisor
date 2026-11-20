"""
Site URLs must be configured. They used to fall back to one real property.
"""
from __future__ import annotations

from pathlib import Path

import pytest

import config
import main

PROJECT = Path(__file__).resolve().parent.parent


class TestNoBakedInSite:
    def test_shipped_files_do_not_name_a_real_property(self):
        for rel in (
            "config.py",
            "setup_bing.py",
            "bing_webmaster.py",
            ".env.example",
            "README.md",
            "SETUP.md",
            "wordpress-plugin/INSTALL.md",
        ):
            text = (PROJECT / rel).read_text(encoding="utf-8")
            assert "eagertobehealthy" not in text, rel

    def test_config_defaults_are_empty_strings_in_source(self):
        text = (PROJECT / "config.py").read_text(encoding="utf-8")
        assert 'os.getenv("GSC_SITE_URL", "").strip()' in text
        assert 'os.getenv("WP_SITE_URL", "").strip()' in text
        assert 'os.getenv("BING_SITE_URL", "").strip()' in text

    def test_missing_wordpress_url_is_refused(self, monkeypatch):
        monkeypatch.setattr(config, "WP_SITE_URL", "")
        monkeypatch.setattr(config, "GSC_SITE_URL", "sc-domain:example.com")
        with pytest.raises(SystemExit) as exc:
            main._require_site_urls(main.parse_args(["--demo"]))
        assert "WP_SITE_URL" in str(exc.value)

    def test_demo_does_not_require_search_console(self, monkeypatch):
        monkeypatch.setattr(config, "WP_SITE_URL", "https://www.example.com")
        monkeypatch.setattr(config, "GSC_SITE_URL", "")
        main._require_site_urls(main.parse_args(["--demo"]))

    def test_real_run_requires_search_console(self, monkeypatch):
        monkeypatch.setattr(config, "WP_SITE_URL", "https://www.example.com")
        monkeypatch.setattr(config, "GSC_SITE_URL", "  ")
        with pytest.raises(SystemExit) as exc:
            main._require_site_urls(main.parse_args([]))
        assert "GSC_SITE_URL" in str(exc.value)

    def test_setup_bing_does_not_assume_a_domain(self, monkeypatch, tmp_path, capsys):
        import setup_bing

        env = tmp_path / ".env"
        monkeypatch.setattr(setup_bing, "ENV_PATH", env)
        monkeypatch.setattr(config, "WP_SITE_URL", "")
        rc = setup_bing.main(["setup_bing.py", "secret-key"])
        assert rc == 1
        assert not env.exists()
        captured = capsys.readouterr()
        assert "eagertobehealthy" not in captured.err
        assert "site URL" in captured.err
