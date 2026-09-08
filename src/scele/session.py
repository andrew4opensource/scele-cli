"""Moodle web-services client.

`scele` talks to SCELE through the official Moodle mobile web-service API
(`/webservice/rest/server.php`) authenticated with a token minted from
`/login/token.php`. No HTML scraping, no session cookie, no `sesskey`.
"""

import requests

from . import __version__
from .config import base_url, load_token

USER_AGENT = f"scele-cli/{__version__} (+https://github.com/Andrew4Coding/scele-cli)"

# Moodle exception errorcodes that mean "token is gone / re-login required".
_REAUTH_CODES = {
    "invalidtoken", "invalidtokenexpired", "accessexception",
    "servicenotavailable", "enrolmentrequired",
}


class NotAuthenticatedError(RuntimeError):
    """Raised when there is no token, or the token is rejected by SCELE."""


class RequestFailedError(RuntimeError):
    """Raised when SCELE returns a Moodle-level exception for a call."""


def _flatten(params: dict, prefix: str = "") -> dict:
    """Moodle's REST endpoint wants nested structures as ``key[0][sub]`` keys."""
    out: dict[str, str] = {}
    for key, value in params.items():
        name = f"{prefix}[{key}]" if prefix else str(key)
        if isinstance(value, dict):
            out.update(_flatten(value, name))
        elif isinstance(value, (list, tuple)):
            for i, item in enumerate(value):
                if isinstance(item, (dict, list, tuple)):
                    out.update(_flatten({i: item}, name))
                else:
                    out[f"{name}[{i}]"] = _scalar(item)
        elif value is not None:
            out[name] = _scalar(value)
    return out


def _scalar(v) -> str:
    if isinstance(v, bool):
        return "1" if v else "0"
    return str(v)


class SceleSession:
    """Holds the token + base URL and makes web-service calls."""

    def __init__(self, token: str | None = None):
        self.base = base_url()
        self.http = requests.Session()
        self.http.headers["User-Agent"] = USER_AGENT
        if token is None:
            stored = load_token()
            token = stored["token"] if stored else None
        self.token = token
        self._site_info: dict | None = None
        self._contents: dict[int, list] = {}

    # ------------------------------------------------------------------ calls

    def ws(self, wsfunction: str, **params):
        """Invoke one web-service function; return its decoded JSON payload.

        Moodle 'exception' payloads become RequestFailedError, except the
        token-expiry family which becomes NotAuthenticatedError.
        """
        if not self.token:
            raise NotAuthenticatedError("not authenticated; run `scele login`")
        payload = {
            "wstoken": self.token,
            "wsfunction": wsfunction,
            "moodlewsrestformat": "json",
            "moodlewssettingfilter": "true",
            "moodlewssettingfileurl": "true",
            **_flatten(params),
        }
        resp = self.http.post(
            f"{self.base}/webservice/rest/server.php", data=payload, timeout=45
        )
        resp.raise_for_status()
        data = resp.json() if resp.content else None
        if isinstance(data, dict) and data.get("exception"):
            code = data.get("errorcode", "")
            message = data.get("message") or data.get("exception") or "request failed"
            if code in _REAUTH_CODES:
                raise NotAuthenticatedError(f"{message} — run `scele login`")
            raise RequestFailedError(f"{wsfunction}: {message}")
        return data

    # ------------------------------------------------------------------ identity

    def site_info(self, refresh: bool = False) -> dict:
        if self._site_info is None or refresh:
            self._site_info = self.ws("core_webservice_get_site_info")
        return self._site_info

    def course_contents(self, course_id: int) -> list:
        """`core_course_get_contents` for a course, memoised for this session."""
        cid = int(course_id)
        if cid not in self._contents:
            self._contents[cid] = self.ws("core_course_get_contents", courseid=cid) or []
        return self._contents[cid]

    def userid(self) -> int:
        return int(self.site_info()["userid"])

    def is_authenticated(self) -> bool:
        try:
            self.site_info(refresh=True)
            return True
        except (NotAuthenticatedError, RequestFailedError, requests.RequestException):
            return False

    # ------------------------------------------------------------------ files

    def pluginfile_url(self, file_url: str) -> str:
        """Turn a webservice pluginfile URL into a token-authenticated one."""
        url = file_url if file_url.startswith("http") else f"{self.base}/{file_url.lstrip('/')}"
        if "pluginfile.php" in url:
            path = url.split("pluginfile.php", 1)[1].split("?", 1)[0]
            url = f"{self.base}/webservice/pluginfile.php{path}"
        sep = "&" if "?" in url else "?"
        return f"{url}{sep}token={self.token}"
