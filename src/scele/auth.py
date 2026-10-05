"""Terminal login that mints a Moodle web-service token.

Uses Moodle's official mobile-app flow: POST username + password to
`/login/token.php` (`service=moodle_mobile_app`), then verify the token with
`core_webservice_get_site_info`. The password is sent once to SCELE over HTTPS
and never written to disk — only the resulting token is saved, and only after it
verifies. A failed login leaves any existing token untouched.

Credentials come from the prompt (password hidden) or from
`SCELE_USERNAME` / `SCELE_PASSWORD` for automation.
"""

import os
import sys
from getpass import getpass

import requests

from .config import base_url, save_token, ws_service
from .output import fail
from .session import SceleSession


def _say(msg: str = "") -> None:
    print(msg, file=sys.stderr)


def _prompt(label: str, secret: bool = False) -> str:
    if not sys.stdin.isatty():
        return sys.stdin.readline().strip()
    return (getpass(label) if secret else input(label)).strip()


def terminal_login(username: str | None = None, password: str | None = None) -> int:
    """Mint and store a web-service token from a username/password."""
    base = base_url()

    username = username or os.environ.get("SCELE_USERNAME") or _prompt("SCELE username: ")
    password = password or os.environ.get("SCELE_PASSWORD") or _prompt("SCELE password: ", secret=True)
    if not username or not password:
        fail("username and password are required", code="login_failed")

    try:
        resp = requests.post(
            f"{base}/login/token.php",
            data={"username": username, "password": password, "service": ws_service()},
            timeout=30,
        )
        resp.raise_for_status()
        body = resp.json()
    except requests.RequestException as e:
        fail(f"could not reach {base}: {e}", code="request_failed")
    except ValueError:
        fail("unexpected response from /login/token.php", code="login_failed")

    if not body.get("token"):
        reason = body.get("error") or body.get("errorcode") or "check your username and password"
        fail(f"login failed: {reason}", code="login_failed")

    session = SceleSession(token=body["token"])
    try:
        info = session.site_info(refresh=True)
    except Exception as e:  # noqa: BLE001 - any verification failure aborts the save
        fail(f"login failed: token not usable ({e})", code="login_failed")

    save_token(body["token"], username=info.get("username") or username,
               private_token=body.get("privatetoken", ""))
    _say(f"Logged in as {info.get('fullname') or username}. Saved token.")
    return 0
