---
name: scele
description: >-
  Use when the user wants to read or act on SCELE — the Moodle at Fakultas Ilmu Komputer
  Universitas Indonesia (scele.cs.ui.ac.id). Covers listing their courses, browsing the
  course catalog, reading a course outline, course people, grades, upcoming deadlines,
  calendar and notifications, listing forum discussions and reading threads, checking
  assignment status/instructions/due dates, submitting text or files to an assignment,
  listing/downloading course resources, reading announcements, and self-enrolling. Backed
  by the `scele` CLI, which returns JSON. Triggers: "my scele", "scele courses", "check my
  assignment on scele", "what's due", "my grades", "read the discussion forum",
  "submit my assignment", "download the slides from scele".
---

# scele

`scele` is a command-line client for SCELE (Moodle at Fasilkom UI). Every command prints
**one JSON document to stdout**; errors print `{"ok":false,"error":<code>,"message":...}`
to stderr and exit non-zero.

## First: is it installed?

```bash
scele --version
```

If missing, install the prebuilt binary (no Python needed):

```bash
curl -fsSL https://raw.githubusercontent.com/Andrew4Coding/scele-cli/main/install-bin.sh | sh
# Windows: irm https://raw.githubusercontent.com/Andrew4Coding/scele-cli/main/install-bin.ps1 | iex
```

With Python instead: `pipx install git+https://github.com/Andrew4Coding/scele-cli.git`.
If `scele` still isn't found after install, add `~/.local/bin` to `PATH` (or open a new shell).

## Discover commands at runtime

```bash
scele schema        # full JSON manifest: every command, its args, its return shape
```

Treat `scele schema` as the source of truth — parse it rather than hard-coding.

## Auth

```bash
scele whoami                       # {"ok":true,"authenticated":true,"user":...} when ready
scele login                        # prompts username + password (no browser, no CAPTCHA)
SCELE_USERNAME=.. SCELE_PASSWORD=.. scele login    # non-interactive
```

`login` exchanges the password for a Moodle web-service token; only the token is stored.
If any command returns `{"error":"not_authenticated"}`, the token was rejected — ask the
user to run `scele login` again. Wrong password → `login_failed`. An account that only
signs in through an external SSO page cannot mint a token.

## ID flow

```
scele courses                  -> course id            (e.g. 4234)
scele course 4234              -> activities w/ cmid    (assignment / resource module ids)
scele forums 4234              -> forum cmid
scele forum <forum-cmid>       -> discussions w/ id (d)
scele thread <d>               -> posts (with parent + depth)
```

`assignment <cmid>` / `download <cmid>` take an activity cmid.
`assignment-detail <ref>` / `submit <ref>` take an assignment ref (instance id *or* cmid).

## Commands

Read-only: `courses`, `course-detail <id>`, `people <id>`, `grades <id>`,
`course-updates <id>`, `deadlines`, `calendar`, `notifications`, `categories [--id N]`,
`category <id>`, `course <id>`, `forums <id>`, `forum <id> [--limit N]`, `thread <d>`,
`assignments <id>`, `assignment <cmid>`, `assignment-detail <ref>`,
`resources <id>`, `announcements`, `schema`, `whoami`, `logout`.

`scele tui` launches an interactive terminal UI over the same data (needs the `[tui]`
extra: `pipx inject scele-cli textual`); it prints no JSON document.

`scele update [VERSION] [--check] [--force]` reinstalls scele at the latest release (or
`VERSION`) using the method it was installed with (binary, pipx, pip, npm). `--check` only
reports `current` vs `target`. It also refreshes any installed copy of this skill
(`~/.claude/skills/scele/`, `./.claude/skills/scele/`) to the same release; see `skill_updated`. Don't run it unless the user asks.

Writes — confirm with the user first; `post`/`reply`/`submit` also need `--yes`:
`enrol <course> [--key K]`, `subscribe <forum> [--off]`,
`post <forum> --subject S --message M --yes`, `reply <post> --message M [--subject S] --yes`,
`submit <ref> (--text T | --file PATH) [--draft] --yes`,
`download <cmid|pluginfile-url> [-o dir]`.

Watch — re-run any command on an interval and report exact line-level output changes:
`scele watch <cmd...> [--interval N] [--webhook URL] [--webhook-header 'K: V'] [--on start|change] [-d]`,
`scele watch ls`, `scele watch run <name>`, `scele watch logs <name>`,
`scele watch rm <name>`, `scele watch clear`, `scele watch rename <name> <new>`.
A foreground `scele watch <cmd>` streams newline-delimited JSON events; `-d` runs it in
the background (POSIX). Change events carry a git-style `diff` plus the full `snapshot`.
A watch exists only while running — stopping it deletes it, and `ls` prunes dead ones.

## Examples

```bash
scele -c courses | jq -r '.[] | "\(.id)\t\(.shortname)\t\(.name)"'
scele -c deadlines --days 14 | jq -r '.[] | "\(.when)\t\(.course)\t\(.name)"'
scele -c grades 4234 | jq -r '.[] | "\(.item): \(.grade)"'
scele -c assignment 222043 | jq '.fields'
scele -c thread 62493 | jq -r '.[] | "\(.depth * "  ")\(.author): \(.body)"'
```

`-c` (before the subcommand) gives single-line JSON.

## Notes

- Dates render as `YYYY-MM-DD HH:MM WIB`; HTML bodies are flattened to plain text.
- `thread` posts carry `parent` and `depth` (0 = discussion starter) — reply to the exact post.
- A `news` forum with no posts legitimately returns `[]`.
- `forum` / `announcements` accept `--limit`; `thread` returns the whole thread.
- Never pass credentials on the command line; use the prompt or the env vars.
