#!/usr/bin/env python3
"""
One-time Bing Webmaster setup (free).

1. Open https://www.bing.com/webmasters and sign in
2. Add and verify your site
3. Settings (gear) → API Access → Generate / copy API key
4. From this project, with the virtualenv active:

     python setup_bing.py YOUR_API_KEY https://www.example.com/

The site URL must match the property Bing verified (www and a trailing
slash, if that is how Bing lists it). If you omit the URL, WP_SITE_URL
from .env is used and printed. There is no built-in domain.

Writes BING_API_KEY and BING_SITE_URL into .env and tests the connection.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ENV_PATH = ROOT / ".env"


def _upsert_env(key: str, value: str) -> None:
    text = ENV_PATH.read_text(encoding="utf-8") if ENV_PATH.exists() else ""
    line = f"{key}={value}"
    pattern = re.compile(rf"^{re.escape(key)}=.*$", re.MULTILINE)
    if pattern.search(text):
        text = pattern.sub(line, text)
    else:
        if text and not text.endswith("\n"):
            text += "\n"
        text += f"\n{line}\n"
    # Ensure USE_BING=1
    if re.search(r"^USE_BING=", text, re.MULTILINE):
        text = re.sub(r"^USE_BING=.*$", "USE_BING=1", text, flags=re.MULTILINE)
    else:
        text += "USE_BING=1\n"
    # .env holds every API secret: owner-only, same as the OAuth token files.
    fd = os.open(ENV_PATH, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[1] in ("-h", "--help"):
        print(__doc__)
        return 0 if len(argv) > 1 else 1

    api_key = argv[1].strip()
    site = argv[2].strip() if len(argv) > 2 else ""
    if not site:
        import config

        site = (config.WP_SITE_URL or "").strip()
        if not site:
            print(
                "No site URL. Pass the URL Bing verified, for example:\n"
                "  python setup_bing.py YOUR_API_KEY https://www.example.com/\n"
                "Or set WP_SITE_URL in .env first. This script does not "
                "assume a domain.",
                file=sys.stderr,
            )
            return 1
        print(f"No site URL given; using WP_SITE_URL={site}")
    if not site.endswith("/"):
        # Bing often stores verified sites with trailing slash
        site_slash = site + "/"
    else:
        site_slash = site

    _upsert_env("BING_API_KEY", api_key)
    _upsert_env("BING_SITE_URL", site_slash)
    print(f"Wrote BING_API_KEY and BING_SITE_URL={site_slash} to {ENV_PATH}")

    # Reload config after writing .env
    import importlib
    import config

    importlib.reload(config)
    config.BING_API_KEY = api_key
    config.BING_SITE_URL = site_slash

    import bing_webmaster

    # Try with trailing slash, then without
    for candidate in (site_slash, site_slash.rstrip("/"), site):
        config.BING_SITE_URL = candidate
        ok, msg = bing_webmaster.test_connection()
        print(f"  test siteUrl={candidate!r}: {msg}")
        if ok:
            _upsert_env("BING_SITE_URL", candidate)
            print("\nBing is ready (free). Run: ./run.sh --no-cooldown")
            return 0

    print(
        "\nAPI key saved but connection failed.\n"
        "In Bing Webmaster → Settings → API Access, confirm the key.\n"
        "Site URL must match verification exactly "
        "(try with/without www and trailing slash).",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
