"""
One-time OAuth setup for headless servers.

Requires an SSH tunnel from your local machine first:
  ssh -L 4567:localhost:4567 aiuser@<server-ip>

Then run:
  python authorize.py
Open the printed URL in your local browser, sign in, and the
token will be saved automatically to token.json.
"""
import os
from google_auth_oauthlib.flow import InstalledAppFlow
import config

_SCOPES = ["https://www.googleapis.com/auth/webmasters.readonly"]
_TOKEN_FILE = "token.json"
_PORT = 4567


def main():
    flow = InstalledAppFlow.from_client_secrets_file(config.GSC_CREDENTIALS_FILE, _SCOPES)
    print("\nOpen the URL below in your browser (SSH tunnel must be active on port 4567):\n")
    creds = flow.run_local_server(port=_PORT, open_browser=False)
    with open(_TOKEN_FILE, "w") as f:
        f.write(creds.to_json())
    print(f"\ntoken.json saved. Run `python main.py` to generate your report.")


if __name__ == "__main__":
    main()
