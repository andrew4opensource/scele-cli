"""Self-describing manifest so an agent can discover every command and its I/O shape.

`scele schema` prints this as JSON. Keep RETURNS / EXAMPLES in sync when adding commands.
"""

import dataclasses

from . import __version__, models
from .config import base_url

RETURNS: dict[str, str] = {
    "login": "ActionResult",
    "logout": "ActionResult",
    "whoami": "{ok: bool, authenticated: bool, base_url: string, user: string, "
              "userid: integer, username: string, token: object}",
    "courses": "Course[]",
    "course-detail": "CourseDetail",
    "people": "Person[]",
    "grades": "Grade[]",
    "course-updates": "{course_id, since_days, updated: {cmid, module, changed}[]}",
    "deadlines": "Deadline[]",
    "calendar": "CalendarEvent[]",
    "notifications": "Notification[]",
    "categories": "Category[]",
    "category": "Course[]",
    "course": "Section[]",
    "forums": "Activity[]",
    "forum": "Discussion[]",
    "thread": "Post[]",
    "assignments": "AssignmentInfo[]",
    "assignment": "AssignmentStatus",
    "assignment-detail": "AssignmentInfo",
    "submit": "ActionResult & {stage: string, warnings: object[]}",
    "resources": "Resource[]",
    "announcements": "Announcement[]",
    "enrol": "ActionResult",
    "subscribe": "ActionResult & {subscribed: bool}",
    "post": "ActionResult & {url: string}",
    "reply": "ActionResult & {url: string}",
    "download": "ActionResult & {path: string}",
    "skill": "ActionResult & {path: string, scope: string}",
    "update": "ActionResult & {method: string, current: string, target: string, updated: bool, "
              "update_available?: bool, pending?: bool, skill_updated?: string[], skill_error?: string}",
    "tui": "launches the interactive terminal UI (no stdout document)",
    "watch": "subcommands: start -> ActionResult & {name, detached, pid?}; "
             "ls -> {name, command, interval, status, last_change, tick_count}[] "
             "(running only; stopped watches are pruned); run -> WatchEvent; "
             "rm/rename -> ActionResult; clear -> ActionResult & {removed: string[]}; "
             "logs -> WatchEvent[]. A stopped watch is deleted, not kept. "
             "A foreground `watch <cmd>` streams newline-delimited WatchEvent docs.",
    "schema": "this document",
}

EXAMPLES: dict[str, str] = {
    "login": "SCELE_USERNAME=you SCELE_PASSWORD=secret scele login",
    "logout": "scele logout",
    "whoami": "scele whoami",
    "courses": "scele courses",
    "course-detail": "scele course-detail 4234",
    "people": "scele people 4234",
    "grades": "scele grades 4234",
    "course-updates": "scele course-updates 4234 --since-days 14",
    "deadlines": "scele deadlines --days 14",
    "calendar": "scele calendar --days-ahead 30",
    "notifications": "scele notifications --limit 20",
    "categories": "scele categories --id 31",
    "category": "scele category 176",
    "course": "scele course 4234",
    "forums": "scele forums 4234",
    "forum": "scele forum 17474",
    "thread": "scele thread 62493",
    "assignments": "scele assignments 4234",
    "assignment": "scele assignment 222043",
    "assignment-detail": "scele assignment-detail 222043",
    "submit": "scele submit 55010 --text 'my answer' --yes",
    "resources": "scele resources 4234",
    "announcements": "scele announcements",
    "enrol": "scele enrol 4128 --key secret",
    "subscribe": "scele subscribe 17474",
    "post": "scele post 17474 --subject 'Hi' --message 'Hello' --yes",
    "reply": "scele reply 553756 --message 'Thanks' --yes",
    "download": "scele download 222038 -o ./dl",
    "skill": "scele skill [--project] [--uninstall]",
    "update": "scele update [VERSION] [--check]",
    "tui": "scele tui",
    "watch": "scele watch deadlines --interval 600 --webhook https://hooks.example/x -d",
}

_PY_TO_JSON = {str: "string", int: "integer", float: "number", bool: "boolean", dict: "object"}


def _type_name(tp) -> str:
    if tp in _PY_TO_JSON:
        return _PY_TO_JSON[tp]
    origin = getattr(tp, "__args__", None)
    if origin:
        inner = [a for a in origin if a is not type(None)]
        base = str(getattr(tp, "__origin__", "")).replace("<class '", "").replace("'>", "")
        if base == "list":
            return f"{_type_name(inner[0])}[]"
        if base == "dict":
            return f"map<{_type_name(inner[0])}, {_type_name(inner[1])}>"
        if len(inner) == 1:
            return f"{_type_name(inner[0])}?"
    return getattr(tp, "__name__", str(tp))


def _models() -> dict[str, dict]:
    out = {}
    for name in dir(models):
        obj = getattr(models, name)
        if dataclasses.is_dataclass(obj) and isinstance(obj, type):
            out[name] = {f.name: _type_name(f.type) for f in dataclasses.fields(obj)}
    if "AssignmentStatus" in out:
        out["AssignmentStatus"]["files"] = "{name: string, url: string}[]"
    for key in ("AssignmentInfo",):
        if key in out:
            out[key]["attachments"] = "{filename: string, filesize: integer, fileurl: string}[]"
    if "CourseDetail" in out:
        out["CourseDetail"]["teachers"] = "{id: string, name: string}[]"
    out["ActionResult"] = {"ok": "boolean", "action": "string", "...": "command-specific fields"}
    return out


def build(group) -> dict:
    """Introspect the click command group into a JSON-serializable manifest."""
    commands = []
    for name, cmd in sorted(group.commands.items()):
        args, opts = [], []
        for p in cmd.params:
            entry = {"name": p.name, "required": bool(getattr(p, "required", False))}
            if p.param_type_name == "argument":
                args.append(entry)
            else:
                entry["flags"] = list(p.opts)
                entry["is_flag"] = bool(getattr(p, "is_flag", False))
                if getattr(p, "help", None):
                    entry["help"] = p.help
                opts.append(entry)
        commands.append({
            "name": name,
            "summary": (cmd.help or "").strip().split("\n")[0],
            "arguments": args,
            "options": opts,
            "returns": RETURNS.get(name, "object"),
            "example": EXAMPLES.get(name, f"scele {name}"),
        })
    return {
        "tool": "scele",
        "version": __version__,
        "description": "Read/write client for SCELE (Moodle) at Fasilkom UI.",
        "base_url": base_url(),
        "output_contract": {
            "stdout": "exactly one logical document per invocation; table on a terminal, "
                      "plain JSON when piped/redirected (or with -f json/yaml/table)",
            "stderr": "on failure: {\"ok\": false, \"error\": <code>, \"message\": <text>}",
            "exit_code": "0 on success, 1 on any error",
            "format_flag": "-f / --format: auto (default), json, yaml, table",
            "compact_flag": "-c / --compact (before the subcommand) for single-line JSON",
            "note": "`scele schema` itself always prints JSON",
        },
        "auth": {
            "mechanism": "Moodle mobile web-service token, minted from /login/token.php",
            "setup": "scele login  (prompts for username + password; no browser, no CAPTCHA)",
            "non_interactive": "set SCELE_USERNAME and SCELE_PASSWORD, then run `scele login`",
            "check": "scele whoami",
            "store": "~/.config/scele/token.json  (token only; the password is never stored)",
            "error_code": "not_authenticated",
        },
        "error_codes": [
            "not_authenticated", "login_failed", "request_failed", "watch_not_found",
        ],
        "id_conventions": {
            "course id": "from `scele courses` / URLs `course/view.php?id=<course>`",
            "cmid (activity/module id)": "from `scele course <id>`; used by assignment/resource",
            "forum id": "activity cmid from `scele forums`/`scele course`; `scele forum` also takes the instance id",
            "discussion id (d)": "from `scele forum <id>` -> `scele thread <d>`",
            "post id": "from `scele thread <d>` -> `scele reply <post>`",
            "assignment ref": "instance id or cmid from `scele assignments <course>`",
        },
        "commands": commands,
        "models": _models(),
    }
