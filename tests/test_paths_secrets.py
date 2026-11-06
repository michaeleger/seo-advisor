"""
B6 — file paths anchor to the project directory, and secret writers are 0600.

Relative paths used to resolve against the caller's cwd, so cron or a
promoted copy run from elsewhere created a fresh empty seo_state.db and could
not find token.json. Token files were written with the process umask.
"""
from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

import config
import db
import gsc

PROJECT = Path(__file__).resolve().parent.parent


def _mode(path) -> int:
    return stat.S_IMODE(os.stat(path).st_mode)


class TestPathAnchors:
    def test_project_dir_is_the_code_directory(self):
        assert config.PROJECT_DIR == PROJECT

    def test_state_and_token_paths_are_anchored(self):
        assert Path(db.DB_PATH) == PROJECT / "seo_state.db"
        assert Path(gsc._TOKEN_FILE) == PROJECT / "token.json"

    def test_relative_env_paths_resolve_against_project(self):
        assert config.project_path("reports") == str(PROJECT / "reports")
        assert config.project_path("/srv/x/reports") == "/srv/x/reports"
        assert Path(config.REPORTS_DIR).is_absolute()
        assert Path(config.GSC_CREDENTIALS_FILE).is_absolute()

    def test_paths_do_not_depend_on_cwd(self, tmp_path):
        code = (
            "import json, config, db, gsc;"
            "print(json.dumps([db.DB_PATH, gsc._TOKEN_FILE,"
            " config.REPORTS_DIR, config.GSC_CREDENTIALS_FILE]))"
        )
        env = {**os.environ, "PYTHONPATH": str(PROJECT)}
        out = subprocess.run(
            [sys.executable, "-c", code], cwd=tmp_path, env=env,
            capture_output=True, text=True, check=True,
        ).stdout
        for p in json.loads(out.strip().splitlines()[-1]):
            assert Path(p).is_absolute()
            assert not Path(p).is_relative_to(tmp_path)

    def test_missing_token_error_is_still_auth_fatal(self, monkeypatch, tmp_path):
        monkeypatch.setattr(gsc, "_TOKEN_FILE", str(tmp_path / "token.json"))
        with pytest.raises(FileNotFoundError) as info:
            gsc._get_credentials()
        assert gsc.is_auth_fatal(info.value)


class TestPrivateWrites:
    def test_new_file_is_0600(self, tmp_path):
        path = tmp_path / "token.json"
        config.write_private_text(path, "{}")
        assert _mode(path) == 0o600
        assert path.read_text() == "{}"

    def test_existing_world_readable_file_is_tightened(self, tmp_path):
        path = tmp_path / "token.json"
        path.write_text("old")
        path.chmod(0o644)
        config.write_private_text(path, "new")
        assert _mode(path) == 0o600
        assert path.read_text() == "new"

    def test_symlink_is_followed_not_replaced(self, tmp_path):
        real = tmp_path / "real.json"
        real.write_text("old")
        link = tmp_path / "link.json"
        link.symlink_to(real)
        config.write_private_text(link, "new")
        assert link.is_symlink()
        assert real.read_text() == "new"
        assert _mode(real) == 0o600

    def test_gsc_token_refresh_writes_0600(self, monkeypatch, tmp_path):
        token = tmp_path / "token.json"
        token.write_text("{}")
        token.chmod(0o644)

        class Creds:
            expired = True
            refresh_token = "r"
            valid = False

            def refresh(self, _request):
                self.valid = True

            def to_json(self):
                return '{"token": "t"}'

        monkeypatch.setattr(gsc, "_TOKEN_FILE", str(token))
        monkeypatch.setattr(
            gsc.Credentials, "from_authorized_user_file",
            staticmethod(lambda *_a, **_k: Creds()),
        )
        gsc._get_credentials()
        assert _mode(token) == 0o600
        assert token.read_text() == '{"token": "t"}'

    def test_ads_env_upsert_writes_0600(self, tmp_path):
        authorize_ads = pytest.importorskip("authorize_ads")
        env = tmp_path / ".env"
        env.write_text("GOOGLE_ADS_CLIENT_ID=old\n")
        env.chmod(0o644)
        authorize_ads._upsert_env(env, {"GOOGLE_ADS_CLIENT_ID": "new"})
        assert _mode(env) == 0o600
        assert env.read_text() == "GOOGLE_ADS_CLIENT_ID=new\n"

    def test_bing_env_upsert_writes_0600(self, monkeypatch, tmp_path):
        import setup_bing

        env = tmp_path / ".env"
        env.write_text("BING_API_KEY=old\n")
        env.chmod(0o644)
        monkeypatch.setattr(setup_bing, "ENV_PATH", env)
        setup_bing._upsert_env("BING_API_KEY", "new")
        assert _mode(env) == 0o600
        assert "BING_API_KEY=new" in env.read_text()
