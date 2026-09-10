"""
One-time Google Search Console OAuth — intended to run fully on 5by5.

Recommended (100% on this machine):
  1. Connect with RDP to 5by5 (xRDP on port 3389) so you have a desktop.
  2. Open a terminal on that desktop.
  3. cd ~/projects/seo-advisor && source .venv/bin/activate
  4. python authorize.py
  Chrome opens on 5by5; sign in; token.json is written here.

Optional SSH-tunnel mode (browser on your laptop):
  ssh -L 4567:localhost:4567 aiuser@5by5
  python authorize.py --no-browser
"""
import argparse
import os
import socket
import sys
from google_auth_oauthlib.flow import InstalledAppFlow
import config

_SCOPES = ["https://www.googleapis.com/auth/webmasters.readonly"]
_TOKEN_FILE = "token.json"
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
            "WARNING: DISPLAY is not set. You are probably in a plain SSH session.\n"
            "Google OAuth needs a browser ON 5by5 for localhost to work.\n\n"
            "Do this instead:\n"
            "  1. RDP into 5by5 (port 3389) as aiuser\n"
            "  2. Open Terminal on the desktop\n"
            "  3. cd ~/projects/seo-advisor && source .venv/bin/activate\n"
            "  4. python authorize.py\n\n"
            "Continuing anyway — open the printed URL in Chrome on 5by5 "
            "(RDP desktop), not on your laptop.\n",
            file=sys.stderr,
        )

    flow = InstalledAppFlow.from_client_secrets_file(
        config.GSC_CREDENTIALS_FILE, _SCOPES
    )

    if open_browser:
        print(
            f"\nStarting OAuth on this machine (localhost:{port}).\n"
            f"Chrome should open here on 5by5 — sign in and allow access.\n"
            f"If no window appears, open the URL printed below in a browser "
            f"running ON 5by5 (RDP), not on your laptop.\n"
        )
    else:
        print(
            f"\nListening on localhost:{port} (no browser).\n"
            f"Tunnel from laptop: ssh -L {port}:localhost:{port} aiuser@5by5\n"
            f"Then open the URL below in the laptop browser.\n"
        )

    creds = flow.run_local_server(
        port=port,
        open_browser=open_browser,
        bind_addr="127.0.0.1",
    )
    with open(_TOKEN_FILE, "w") as f:
        f.write(creds.to_json())
    print(f"\ntoken.json saved → {os.path.abspath(_TOKEN_FILE)}")
    print("Run: python main.py")


if __name__ == "__main__":
    main()
