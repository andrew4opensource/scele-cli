"""Background watches: re-run an existing `scele` command on an interval and report
exact line-level changes in its JSON output, optionally to a webhook.

Storage (POSIX): ``~/.config/scele/watches/<name>/``
  watch.json   -- immutable config {name, command, interval, webhooks, headers, on, created}
  state.json   -- {last_hash, last_run, last_change, tick_count}
  last_canonical.txt -- canonical text of the last capture (for diffing)
  events.jsonl -- append-only log of change / error / webhook events
  daemon.pid   -- {pid, started} for the detached process, when running detached
  daemon.log   -- stdout/stderr of the detached process
"""

import difflib
import hashlib
import json
import os
import re
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from .config import watches_dir

MIN_INTERVAL = 30
DEFAULT_INTERVAL = 300
MAX_EVENTS = 1000
_VOLATILE_KEYS = {"sesskey", "token", "token_preview", "age_days"}
_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")


class WatchError(RuntimeError):
    """A watch could not be found, or its name is invalid."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


# ---------------------------------------------------------------- canonical / diff

def _strip_volatile(obj):
    if isinstance(obj, dict):
        return {k: _strip_volatile(v) for k, v in obj.items() if k not in _VOLATILE_KEYS}
    if isinstance(obj, list):
        return [_strip_volatile(x) for x in obj]
    return obj


def canonical(obj) -> str:
    """Stable, pretty JSON text of a command result (volatile fields removed)."""
    return json.dumps(_strip_volatile(obj), ensure_ascii=False, sort_keys=True, indent=2)


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def unified(old: str, new: str, name: str) -> str:
    """git-style unified diff (3 lines of context) between two canonical texts."""
    lines = difflib.unified_diff(
        old.splitlines(), new.splitlines(),
        fromfile=f"{name}@prev", tofile=f"{name}@now", lineterm="", n=3,
    )
    return "\n".join(lines)


def _diff_counts(diff: str) -> tuple[int, int]:
    added = sum(1 for ln in diff.splitlines() if ln.startswith("+") and not ln.startswith("+++"))
    removed = sum(1 for ln in diff.splitlines() if ln.startswith("-") and not ln.startswith("---"))
    return added, removed


# ---------------------------------------------------------------- command capture

def run_command(command: list[str]) -> dict:
    """Run ``scele -c <command...>`` in a child process, return a result dict.

    {"ok": True, "data": <parsed json>} or
    {"ok": False, "error": <code>, "message": <text>}.
    """
    proc = subprocess.run(
        [sys.executable, "-m", "scele", "-c", *command],
        capture_output=True, text=True, timeout=120,
    )
    if proc.returncode == 0:
        try:
            return {"ok": True, "data": json.loads(proc.stdout)}
        except json.JSONDecodeError as e:
            return {"ok": False, "error": "request_failed",
                    "message": f"unparseable output: {e}"}
    try:
        err = json.loads(proc.stderr)
        return {"ok": False, "error": err.get("error", "request_failed"),
                "message": err.get("message", proc.stderr.strip())}
    except json.JSONDecodeError:
        return {"ok": False, "error": "request_failed",
                "message": (proc.stderr or proc.stdout).strip()}


# ---------------------------------------------------------------- storage

def _slug(name: str) -> str:
    if name in (".", "..") or not _NAME_RE.match(name or ""):
        raise WatchError(f"invalid watch name {name!r}: use letters, digits, '.', '_', '-'")
    return name


def _dir(name: str) -> Path:
    return watches_dir() / _slug(name)


def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _write_json(path: Path, obj) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def _append_event(name: str, event: dict) -> None:
    event = {"at": _now(), **event}
    path = _dir(name) / "events.jsonl"
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(event, ensure_ascii=False) + "\n")
    _trim_events(path)


def _trim_events(path: Path) -> None:
    """Keep events.jsonl bounded; rewrite only once it drifts well past the cap."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    if len(lines) > MAX_EVENTS * 2:
        path.write_text("\n".join(lines[-MAX_EVENTS:]) + "\n", encoding="utf-8")


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _status(d: Path) -> str:
    pid_info = _read_json(d / "daemon.pid", None)
    if pid_info and _pid_alive(pid_info.get("pid", -1)):
        return "running"
    state = _read_json(d / "state.json", {})
    last = _last_event(d.name)
    if last and last.get("event") == "error":
        return "error"
    return "stopped" if state else "idle"


def _last_event(name: str) -> dict | None:
    path = _dir(name) / "events.jsonl"
    if not path.exists():
        return None
    lines = path.read_text(encoding="utf-8").splitlines()
    for line in reversed(lines):
        if line.strip():
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                return None
    return None


# ---------------------------------------------------------------- webhook

def deliver(url: str, headers: dict, payload: dict, retries: int = 3) -> dict:
    """POST payload as JSON, retrying with exponential backoff. Returns a log dict."""
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    hdrs = {"Content-Type": "application/json", "User-Agent": "scele-cli watch", **headers}
    last_err = ""
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, data=body, headers=hdrs, method="POST")
            with urllib.request.urlopen(req, timeout=5) as resp:
                return {"event": "webhook", "url": url, "status": resp.status}
        except urllib.error.HTTPError as e:
            last_err = f"HTTP {e.code}"
        except (urllib.error.URLError, OSError, TimeoutError) as e:
            last_err = str(e)
        if attempt < retries - 1:
            time.sleep(2 ** attempt)
    return {"event": "webhook", "url": url, "error": last_err}


def _fire_webhooks(cfg: dict, payload: dict) -> None:
    headers = _parse_headers(cfg.get("headers", []))
    for url in cfg.get("webhooks", []):
        _append_event(cfg["name"], deliver(url, headers, payload))


def _parse_headers(pairs: list[str]) -> dict:
    out = {}
    for p in pairs:
        if ":" in p:
            k, _, v = p.partition(":")
            out[k.strip()] = v.strip()
    return out


# ---------------------------------------------------------------- lifecycle

def create(name: str, command: list[str], *, interval: int, webhooks: list[str],
           headers: list[str], on: str) -> dict:
    """Write a new watch config. Raises WatchError if one is already running."""
    d = _dir(name)
    if d.exists() and _status(d) == "running":
        raise WatchError(f"watch {name!r} is already running; stop it first")
    d.mkdir(parents=True, exist_ok=True)
    cfg = {
        "name": _slug(name),
        "command": list(command),
        "interval": max(MIN_INTERVAL, int(interval)),
        "webhooks": list(webhooks),
        "headers": list(headers),
        "on": on,
        "created": _now(),
    }
    _write_json(d / "watch.json", cfg)
    return cfg


def spawn(name: str) -> dict:
    """Start the watch loop for `name` as a detached background process."""
    d = _dir(name)
    log = (d / "daemon.log").open("a", encoding="utf-8")
    proc = subprocess.Popen(
        [sys.executable, "-m", "scele", "watch", "_run", name],
        stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
        start_new_session=True,
    )
    _write_json(d / "daemon.pid", {"pid": proc.pid, "started": _now()})
    return {"pid": proc.pid}


def tick(name: str) -> dict:
    """Run one capture; record a change/error event and fire webhooks as needed.

    Returns the event dict written (or an ``event: none`` dict when nothing changed).
    """
    d = _dir(name)
    cfg = _read_json(d / "watch.json", None)
    if cfg is None:
        raise WatchError(f"no such watch: {name}")
    state = _read_json(d / "state.json", {})
    result = run_command(cfg["command"])
    ts = _now()

    if not result["ok"]:
        event = {"event": "error", "watch": name, "command": cfg["command"],
                 "error": result["error"], "message": result["message"]}
        _append_event(name, event)
        _fire_webhooks(cfg, event)
        state.update(last_run=ts, tick_count=state.get("tick_count", 0) + 1)
        _write_json(d / "state.json", state)
        return event

    canonical_path = d / "last_canonical.txt"
    new_text = canonical(result["data"])
    new_hash = _hash(new_text)
    prev_text = state.get("last_canonical") or _read_text(canonical_path)
    first_run = "last_hash" not in state
    changed = (not first_run) and new_hash != state.get("last_hash")

    state.pop("last_canonical", None)
    state.update(last_run=ts, last_hash=new_hash,
                 tick_count=state.get("tick_count", 0) + 1)
    if first_run or changed:
        canonical_path.write_text(new_text, encoding="utf-8")

    event = {"event": "none", "watch": name}
    if changed or (first_run and cfg["on"] == "start"):
        diff = unified(prev_text, new_text, name) if changed else ""
        added, removed = _diff_counts(diff)
        event = {
            "event": "change" if changed else "start",
            "watch": name,
            "command": cfg["command"],
            "added_lines": added,
            "removed_lines": removed,
            "diff": diff,
            "snapshot": result["data"],
        }
        _append_event(name, event)
        _fire_webhooks(cfg, event)
        state["last_change"] = ts

    _write_json(d / "state.json", state)
    return event


def run_loop(name: str, *, stream=None) -> None:
    """Blocking watch loop. Writes NDJSON events to `stream` if given."""
    d = _dir(name)
    cfg = _read_json(d / "watch.json", None)
    if cfg is None:
        raise WatchError(f"no such watch: {name}")

    stop = {"flag": False}

    def _handle(_signum, _frame):
        stop["flag"] = True

    signal.signal(signal.SIGTERM, _handle)
    signal.signal(signal.SIGINT, _handle)

    try:
        while not stop["flag"]:
            event = tick(name)
            if stream is not None and event.get("event") != "none":
                stream.write(json.dumps(event, ensure_ascii=False) + "\n")
                stream.flush()
            for _ in range(cfg["interval"]):
                if stop["flag"]:
                    break
                time.sleep(1)
    finally:
        # A watch exists only while it runs: once the loop ends, it is gone.
        _delete_dir(d)


def _delete_dir(d: Path) -> None:
    """Best-effort recursive delete of a watch directory."""
    if not d.exists():
        return
    for child in d.iterdir():
        try:
            child.unlink()
        except OSError:
            pass
    try:
        d.rmdir()
    except OSError:
        pass


def stop(name: str) -> bool:
    """Signal a running watch to exit and delete it. Returns True if a live process
    was signalled."""
    d = _dir(name)
    pid_info = _read_json(d / "daemon.pid", None)
    signalled = False
    if pid_info:
        pid = pid_info.get("pid", -1)
        if pid > 0 and pid != os.getpid() and _pid_alive(pid):
            try:
                os.kill(pid, signal.SIGTERM)
                signalled = True
            except ProcessLookupError:
                pass
            for _ in range(50):
                if not _pid_alive(pid):
                    break
                time.sleep(0.1)
    _delete_dir(d)
    return signalled


def remove(name: str) -> bool:
    """Stop a watch (if running) and delete its directory."""
    d = _dir(name)
    if not d.exists():
        raise WatchError(f"no such watch: {name}")
    return stop(name)


def clear() -> list[str]:
    """Stop and delete every watch. Returns the names removed."""
    base = watches_dir()
    names = [d.name for d in sorted(base.iterdir())
             if (d / "watch.json").exists()] if base.exists() else []
    for name in names:
        stop(name)
    return names


def rename(name: str, new_name: str) -> None:
    """Rename a stopped watch."""
    d = _dir(name)
    if not d.exists():
        raise WatchError(f"no such watch: {name}")
    if _status(d) == "running":
        raise WatchError(f"watch {name!r} is running; stop it before renaming")
    target = _dir(new_name)
    if target.exists():
        raise WatchError(f"watch {new_name!r} already exists")
    d.rename(target)
    cfg = _read_json(target / "watch.json", {})
    cfg["name"] = _slug(new_name)
    _write_json(target / "watch.json", cfg)


def info(name: str) -> dict:
    """Full status of one watch."""
    d = _dir(name)
    if not d.exists():
        raise WatchError(f"no such watch: {name}")
    cfg = _read_json(d / "watch.json", {})
    state = _read_json(d / "state.json", {})
    pid_info = _read_json(d / "daemon.pid", None)
    return {
        "name": name,
        "command": cfg.get("command", []),
        "interval": cfg.get("interval"),
        "webhooks": cfg.get("webhooks", []),
        "on": cfg.get("on"),
        "status": _status(d),
        "pid": pid_info.get("pid") if pid_info else None,
        "created": cfg.get("created"),
        "last_run": state.get("last_run"),
        "last_change": state.get("last_change"),
        "tick_count": state.get("tick_count", 0),
    }


def prune() -> list[str]:
    """Delete any watch whose process is no longer running. Returns the names dropped."""
    base = watches_dir()
    dropped = []
    for d in sorted(base.iterdir()) if base.exists() else []:
        if (d / "watch.json").exists() and _status(d) != "running":
            _delete_dir(d)
            dropped.append(d.name)
    return dropped


def listing() -> list[dict]:
    """One summary row per running watch (stopped watches are pruned first)."""
    prune()
    base = watches_dir()
    rows = []
    for d in sorted(base.iterdir()) if base.exists() else []:
        if not (d / "watch.json").exists():
            continue
        cfg = _read_json(d / "watch.json", {})
        state = _read_json(d / "state.json", {})
        rows.append({
            "name": d.name,
            "command": " ".join(cfg.get("command", [])),
            "interval": cfg.get("interval"),
            "status": _status(d),
            "last_change": state.get("last_change"),
            "tick_count": state.get("tick_count", 0),
        })
    return rows


def events(name: str, limit: int = 50) -> list[dict]:
    """Return the last `limit` logged events, newest last."""
    if not _dir(name).exists():
        raise WatchError(f"no such watch: {name}")
    path = _dir(name) / "events.jsonl"
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return out[-limit:]
