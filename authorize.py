"""
One-time Google Search Console OAuth. Writes token.json in this project.

On a machine with a browser (virtualenv already active):
  python authorize.py
  Sign in with the Google account that can read the Search Console property.
  token.json is written here (mode 0600).

Headless server, browser on another computer (callback port 4567):
  ssh -L 4567:localhost:4567 user@your-server
  python authorize.py --no-browser
  Open the printed URL in the browser on the computer that owns the tunnel.
"""
import argparse
import os
import socket
import sys
from google_auth_oauthlib.flow import InstalledAppFlow
import config

_SCOPES = ["https://www.googleapis.com/auth/webmasters.readonly"]
_TOKEN_FILE = config.PROJECT_DIR / "token.json"
_PORT = int(os.getenv("GSC_OAUTH_PORT", "4567"))


def _port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1", port))
            return False
        except OSError:
            return True


def main():
    parser = argparse.ArgumentParser(description="Authorize GSC OAuth → token.json")
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Do not open a browser (use with SSH tunnel from a laptop)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=_PORT,
        help=f"Loopback callback port (default {_PORT})",
    )
    args = parser.parse_args()
    port = args.port
    open_browser = not args.no_browser

    if _port_in_use(port):
        print(
            f"ERROR: port {port} is already in use on this machine.\n"
            f"  Find it:  ss -tlnp | grep {port}\n"
            f"  Kill old authorize: pkill -f 'python authorize.py'\n"
            f"  Or: python authorize.py --port 4568\n",
            file=sys.stderr,
        )
        sys.exit(1)

    if open_browser and not os.environ.get("DISPLAY"):
        print(
            "WARNING: DISPLAY is not set, so a browser on this machine may not open.\n"
            "Google's callback is localhost, so the browser has to reach this process.\n\n"
            "Either:\n"
            "  - Run `python authorize.py` in a desktop session on this machine, or\n"
            f"  - From your computer: ssh -L {port}:localhost:{port} user@this-host\n"
            "    then: python authorize.py --no-browser\n"
            "    and open the printed URL in the browser on your computer.\n\n"
            "Continuing. If a URL is printed, open it in a browser that can reach "
            f"localhost:{port} on this machine.\n",
            file=sys.stderr,
        )

    flow = InstalledAppFlow.from_client_secrets_file(
        config.GSC_CREDENTIALS_FILE, _SCOPES
    )

    if open_browser:
        print(
            f"\nStarting OAuth on this machine (localhost:{port}).\n"
            "A browser should open. Sign in and allow access.\n"
            "If no window appears, open the URL printed below in a browser "
            "on this same machine.\n"
        )
    else:
        print(
            f"\nListening on localhost:{port} (no browser).\n"
            "From the computer with your browser:\n"
            f"  ssh -L {port}:localhost:{port} user@this-host\n"
            "Then open the URL below in that browser.\n"
        )

    creds = flow.run_local_server(
        port=port,
        open_browser=open_browser,
        bind_addr="127.0.0.1",
    )
    config.write_private_text(_TOKEN_FILE, creds.to_json())
    print(f"\ntoken.json saved (mode 0600) → {_TOKEN_FILE}")
    print("Run: python main.py")


if __name__ == "__main__":
    main()
