# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

`scele` — a command-line client for **SCELE** (`https://scele.cs.ui.ac.id/`), the Moodle instance of
Fakultas Ilmu Komputer, Universitas Indonesia. It authenticates with a username/password to mint a
**Moodle mobile web-service token** (`/login/token.php`, `service=moodle_mobile_app`), stores only
that token, and drives SCELE through the official web-service API
(`/webservice/rest/server.php`). No HTML scraping, no session cookie, no `sesskey`.

The `../scele_cli_recorder/` sibling repo (Playwright recorder + `moodle_capture/` fixtures) was used
for the old scraping implementation and is no longer a dependency of anything here.

## Layout

- `src/scele/` — the package (`scele` entry point):
  - `cli.py` — click command surface. `_guard()` wraps every API call so any exception becomes a JSON
    error. `_out()` prints via `output.emit`.
  - `api.py` — one function per command; takes a `SceleSession`, calls one or more web-service
    functions, maps the JSON onto dataclasses in `models.py`.
  - `session.py` — `SceleSession`: holds the token + base URL. `ws(wsfunction, **params)` POSTs to
    `/webservice/rest/server.php`, flattens nested params to Moodle's `key[0][sub]` form, and turns
    Moodle `exception` payloads into `RequestFailedError` (or `NotAuthenticatedError` for the
    token-expiry family). `site_info()`, `userid()`, `is_authenticated()`, `pluginfile_url()`.
  - `auth.py` — `terminal_login`: POST username+password to `/login/token.php`, verify the token with
    `core_webservice_get_site_info`, then save it. Reads creds from prompt (password hidden) or
    `SCELE_USERNAME`/`SCELE_PASSWORD`. **The password is never written to disk**; only the verified
    token is saved; a failed login leaves any existing `token.json` untouched (`login_failed`).
  - `textutil.py` — `clean_html` (Moodle HTML → plain text), `wib`/`until` (epoch → WIB strings /
    countdowns). Used everywhere `api.py` shapes a web-service payload.
  - `models.py` — dataclasses with `to_dict()`.
  - `output.py` — `emit` (one document to stdout: table on a TTY, JSON when piped), `fail` (JSON
    error to stderr, exit 1).
  - `watch.py` — background watches: re-run any `scele` subcommand on an interval, diff its
    canonical JSON output (git-style unified diff, volatile keys like `token` stripped), log events to
    `~/.config/scele/watches/<name>/events.jsonl`, POST changes to configured webhooks.
    POSIX-only detach (`subprocess` + `start_new_session`, PID in `daemon.pid`); no
    reboot persistence. A watch exists only while running: when its loop ends it deletes
    its own directory, and `watch ls` prunes any watch whose process is gone. CLI surface
    is the `watch` group in `cli.py` (`ls`, `run`, `rm`, `clear`, `rename`, `logs`).
  - `config.py` — token store. `~/.config/scele/token.json` (or `$XDG_CONFIG_HOME`) on Unix,
    `%APPDATA%\scele\` on Windows; override with `SCELE_CONFIG_DIR`. Base URL: `SCELE_BASE_URL`.
    WS short name: `SCELE_WS_SERVICE` (default `moodle_mobile_app`).
- `__version__` in `src/scele/__init__.py` is the **single version source**; `pyproject.toml`
  reads it via `[tool.hatch.version]`. Bump it only through `scripts/release.sh <version>`.
- Install paths:
  - `install-bin.sh` / `install-bin.ps1` — raw-content installers: download the prebuilt binary
    from GitHub Releases (latest, or `SCELE_VERSION`), verify SHA-256, drop on PATH. No Python.
  - `install.sh` / `install.ps1` — bootstrap pip+pipx and `pipx install` a checkout/git URL.
    Flags: `--editable`, `--from`, `--uninstall`.
  - `packaging/scele.spec` + `packaging/entry.py` + `scripts/build-binary.sh` — PyInstaller
    one-file build (this OS/arch only; no cross-compile).
  - `.github/workflows/release.yml` — on push to `main`, if `__version__` has no `v<version>`
    tag yet: build binaries on 5 runners + sdist/wheel, push the tag, publish a GitHub Release
    with `checksums.txt`. `workflow_dispatch` with `force` rebuilds an existing version.
    `ci.yml` runs pytest on push/PR.
  - `RELEASING.md` is the operator guide.
- `skills/scele/SKILL.md` — the Agent Skill. Installs via `scele skill` (from `npm install -g scele-cli`),
  `npx scele-cli skill`, or `npx skills add Andrew4Coding/scele-cli`. Keep SKILL.md,
  `AGENTS.md.bak`, and `schema.py` in sync when commands change. `SKILLS.md` documents all install methods.
  - `schema.py` — builds the `scele schema` manifest by introspecting the click group + dataclasses.
- `ENDPOINTS.md` — the web-service functions each command calls.
- `tests/test_api.py` — `api.py` mapping logic against canned web-service payloads (no network).
  `tests/test_schema.py` — the `scele schema` manifest stays complete.

## Output contract (do not break)

- Every command prints **exactly one JSON document to stdout** via `output.emit`. The sole
  exception: a **foreground** `scele watch <cmd>` streams newline-delimited JSON events
  (one `WatchEvent` doc per line). `watch ls/run/rm/rename/logs` stay single-document.
- Errors go to **stderr** as `{"ok": false, "error": <code>, "message": ...}` via `output.fail`, exit 1.
  Codes: `not_authenticated`, `login_failed`, `request_failed`, `watch_not_found`.
- Prompts and notices go to stderr, never stdout.
- `-c/--compact` is a group-level flag for single-line JSON.

## Working on the CLI

```bash
make dev            # python3 -m venv .venv && .venv/bin/pip install -e ".[dev,build]"
make test           # .venv/bin/pytest -q
make binary         # scripts/build-binary.sh -> dist/scele
./install.sh -e     # pipx editable install (puts `scele` on PATH)
```

- Runtime deps are just `requests` + `click`. `beautifulsoup4`/`lxml` are gone.
- Each `api.py` function is one-or-more `s.ws("<wsfunction>", ...)` calls plus a map to a dataclass.
  When adding one, list the web-service function(s) in `ENDPOINTS.md`.
- Nested WS params are passed as plain dict/list; `session._flatten` renders `key[0][sub]` for you.
- Write ops (`enrol`, `post`, `reply`, `subscribe`, `submit`) call state-changing WS functions.
  `post`/`reply`/`submit` require `--yes` or a TTY prompt.
- When you add/rename a command, update `RETURNS` and `EXAMPLES` in `schema.py`
  (`tests/test_schema.py` enforces both), the command list in `skills/scele/SKILL.md`, and `README.md`.

## Notes

- Some forums (e.g. "Class Announcements") legitimately return `[]` — they have no discussions.
- `login` relies on `/login/token.php` accepting a password. This works for manual/LDAP accounts;
  an account behind an external SSO/CAS/SAML login page cannot mint a token this way.
