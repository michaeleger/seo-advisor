"""
One-time OAuth for Google Ads API (Keyword Planner).

Uses PKCE (required by modern Google OAuth). Manual code paste only works if
we keep the code_verifier from the same auth start — this script does that.

On 5by5 RDP (browser on this machine) — simplest:
  cd ~/projects/seo-advisor && source .venv/bin/activate
  python authorize_ads.py

If browser shows "localhost refused to connect":
  1) Leave that URL in the address bar (or copy it)
  2) In the SAME terminal session that printed the Google URL, paste when asked
     OR run:  python authorize_ads.py --finish 'http://localhost:4568/?code=...'

Two-step (SSH without browser):
  python authorize_ads.py --start          # prints Google URL; saves verifier
  # open URL, copy callback
  python authorize_ads.py --finish 'CALLBACK_URL'
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from google_auth_oauthlib.flow import InstalledAppFlow

import config

_SCOPES = ["https://www.googleapis.com/auth/adwords"]
_TOKEN_FILE = Path("ads_token.json")
_PENDING_FILE = Path(".ads_oauth_pending.json")
_PORT = int(os.getenv("GSC_OAUTH_PORT", "4568"))
_REDIRECT = f"http://localhost:{_PORT}/"


def _secrets_file() -> str:
    path = config.GSC_CREDENTIALS_FILE
    if not Path(path).exists():
        print(f"Missing {path}", file=sys.stderr)
        sys.exit(1)
    return path


def _save_env_hints(payload: dict) -> None:
    _TOKEN_FILE.write_text(json.dumps(payload, indent=2))
    # Merge into .env without printing secrets to logs more than once
    env_path = Path(".env")
    lines = {
        "GOOGLE_ADS_CLIENT_ID": payload["client_id"],
        "GOOGLE_ADS_CLIENT_SECRET": payload["client_secret"],
        "GOOGLE_ADS_REFRESH_TOKEN": payload["refresh_token"],
        "USE_KEYWORD_PLANNER": "1",
        "GOOGLE_ADS_GEO_TARGET_IDS": os.getenv("GOOGLE_ADS_GEO_TARGET_IDS", "2840"),
    }
    _upsert_env(env_path, lines)
    print(f"\nSaved {_TOKEN_FILE} and updated .env with OAuth client + refresh token.")
    print("Still required (from Google Ads UI — not from this OAuth step):")
    print("  GOOGLE_ADS_DEVELOPER_TOKEN=...")
    print("  GOOGLE_ADS_CUSTOMER_ID=...")
    print("  # GOOGLE_ADS_LOGIN_CUSTOMER_ID=...  # if MCC manager")
    print("\nThen: ./run.sh --no-cooldown\n")


def _upsert_env(path: Path, values: dict[str, str]) -> None:
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    for key, value in values.items():
        line = f"{key}={value}"
        import re

        pat = re.compile(rf"^{re.escape(key)}=.*$", re.MULTILINE)
        if pat.search(text):
            text = pat.sub(line, text)
        else:
            # also replace commented form
            cpat = re.compile(rf"^#\s*{re.escape(key)}=.*$", re.MULTILINE)
            if cpat.search(text):
                text = cpat.sub(line, text)
            else:
                if text and not text.endswith("\n"):
                    text += "\n"
                text += line + "\n"
    path.write_text(text, encoding="utf-8")


def _make_flow() -> InstalledAppFlow:
    flow = InstalledAppFlow.from_client_secrets_file(_secrets_file(), _SCOPES)
    flow.redirect_uri = _REDIRECT
    # Force a code_verifier for PKCE so --finish can complete later
    if not getattr(flow, "code_verifier", None):
        flow.code_verifier = secrets.token_urlsafe(64)
    return flow


def cmd_start() -> None:
    flow = _make_flow()
    auth_url, state = flow.authorization_url(
        access_type="offline",
        prompt="consent",
    )
    pending = {
        "state": state,
        "code_verifier": flow.code_verifier,
        "redirect_uri": _REDIRECT,
        "client_config_file": _secrets_file(),
        "scopes": _SCOPES,
    }
    _PENDING_FILE.write_text(json.dumps(pending, indent=2))
    print("\n=== Google Ads OAuth (step 1/2) ===\n")
    print("Open this URL in a browser:\n")
    print(auth_url)
    print(
        f"\nAfter you approve, Google redirects to localhost:{_PORT}.\n"
        f"The page may say 'refused to connect' — that is OK.\n"
        f"Copy the FULL address bar URL, then run:\n\n"
        f"  python authorize_ads.py --finish 'PASTE_URL_HERE'\n"
    )
    print(f"(PKCE verifier saved to {_PENDING_FILE} — do not delete until finished)\n")


def cmd_finish(callback_url: str) -> None:
    if not _PENDING_FILE.exists():
        print(
            f"Missing {_PENDING_FILE}. Run: python authorize_ads.py --start",
            file=sys.stderr,
        )
        sys.exit(1)
    pending = json.loads(_PENDING_FILE.read_text())
    cleaned = callback_url.strip().strip("\"'")
    qs = parse_qs(urlparse(cleaned).query)
    if "code" not in qs:
        print("No code= in URL", file=sys.stderr)
        sys.exit(1)
    code = qs["code"][0]
    # state check optional but good
    if "state" in qs and pending.get("state") and qs["state"][0] != pending["state"]:
        print("WARNING: state mismatch — continuing anyway", file=sys.stderr)

    flow = InstalledAppFlow.from_client_secrets_file(
        pending.get("client_config_file") or _secrets_file(),
        pending.get("scopes") or _SCOPES,
    )
    flow.redirect_uri = pending.get("redirect_uri") or _REDIRECT
    flow.code_verifier = pending["code_verifier"]

    try:
        flow.fetch_token(code=code)
    except Exception as exc:
        print(f"Token exchange failed: {exc}", file=sys.stderr)
        print(
            "Start a fresh login: python authorize_ads.py --start",
            file=sys.stderr,
        )
        sys.exit(1)

    creds = flow.credentials
    if not creds.refresh_token:
        print(
            "No refresh_token. Revoke app at https://myaccount.google.com/permissions "
            "then: python authorize_ads.py --start",
            file=sys.stderr,
        )
        sys.exit(1)

    payload = {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": list(creds.scopes or _SCOPES),
    }
    _save_env_hints(payload)
    try:
        _PENDING_FILE.unlink()
    except OSError:
        pass
    print("OAuth complete.")


def cmd_local_server() -> None:
    """Browser on this machine; local server catches the redirect."""
    flow = InstalledAppFlow.from_client_secrets_file(_secrets_file(), _SCOPES)
    print(
        f"\nListening on {_REDIRECT}\n"
        f"Open the printed/opened URL, sign in, allow access.\n"
    )
    try:
        creds = flow.run_local_server(
            port=_PORT,
            open_browser=bool(os.environ.get("DISPLAY")),
            bind_addr="127.0.0.1",
            access_type="offline",
            prompt="consent",
        )
    except OSError as exc:
        print(f"Could not bind port {_PORT}: {exc}", file=sys.stderr)
        print("Use: python authorize_ads.py --start", file=sys.stderr)
        sys.exit(1)

    if not creds.refresh_token:
        print("No refresh_token — revoke app access and retry.", file=sys.stderr)
        sys.exit(1)

    payload = {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": list(creds.scopes or _SCOPES),
    }
    _save_env_hints(payload)


def main() -> None:
    p = argparse.ArgumentParser(description="Google Ads OAuth for Keyword Planner")
    p.add_argument(
        "--start",
        action="store_true",
        help="Step 1: print Google login URL and save PKCE verifier",
    )
    p.add_argument(
        "--finish",
        metavar="CALLBACK_URL",
        help="Step 2: exchange callback URL (needs prior --start)",
    )
    p.add_argument(
        "--callback-url",
        metavar="URL",
        help="Alias for --finish",
    )
    args = p.parse_args()

    finish_url = args.finish or args.callback_url
    if finish_url:
        # If no pending verifier, explain why old paste failed
        if not _PENDING_FILE.exists():
            print(
                "This callback cannot be used alone (Google PKCE).\n"
                "Run a fresh pair:\n"
                "  python authorize_ads.py --start\n"
                "  # open URL, copy callback\n"
                "  python authorize_ads.py --finish 'CALLBACK_URL'\n",
                file=sys.stderr,
            )
            sys.exit(1)
        cmd_finish(finish_url)
        return

    if args.start:
        cmd_start()
        return

    # Default: local server if display, else two-step start
    if os.environ.get("DISPLAY"):
        cmd_local_server()
    else:
        print("No DISPLAY — using two-step OAuth.\n")
        cmd_start()


if __name__ == "__main__":
    main()
