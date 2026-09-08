"""Tests for the background `watch` command (no network, no real subprocess)."""

import json
import os

import pytest

from scele import config, watch


def _mark_running(name):
    """Write a daemon.pid pointing at this (alive) process so the watch reads as running."""
    watch._write_json(watch._dir(name) / "daemon.pid", {"pid": os.getpid(), "started": "now"})


@pytest.fixture(autouse=True)
def _tmp_watches(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "WATCHES_DIR", tmp_path / "watches")


def _capture(seq):
    """Return a fake run_command that yields successive results from `seq`."""
    it = iter(seq)
    last = [None]

    def _fn(_command):
        try:
            last[0] = next(it)
        except StopIteration:
            pass
        return last[0]

    return _fn


def _ok(data):
    return {"ok": True, "data": data}


# ---------------------------------------------------------------- canonical / diff

def test_canonical_is_stable_and_strips_sesskey():
    a = canonical_input = {"b": 1, "a": 2, "sesskey": "xxx"}
    text = watch.canonical(a)
    assert "sesskey" not in text
    assert watch.canonical({"a": 2, "b": 1}) == text


def test_unified_diff_shows_exact_lines():
    old = watch.canonical({"status": "not submitted", "due": "2026-09-05"})
    new = watch.canonical({"status": "submitted", "due": "2026-09-05"})
    diff = watch.unified(old, new, "t")
    assert '-  "status": "not submitted"' in diff
    assert '+  "status": "submitted"' in diff
    assert "@@" in diff


# ---------------------------------------------------------------- tick lifecycle

def test_first_tick_is_not_a_change(monkeypatch):
    monkeypatch.setattr(watch, "run_command", _capture([_ok([{"id": 1}])]))
    watch.create("w", ["courses"], interval=30, webhooks=[], headers=[], on="change")
    assert watch.tick("w")["event"] == "none"


def test_change_produces_diff_event(monkeypatch):
    monkeypatch.setattr(watch, "run_command",
                        _capture([_ok([{"id": 1, "name": "A"}]),
                                  _ok([{"id": 1, "name": "B"}])]))
    watch.create("w", ["courses"], interval=30, webhooks=[], headers=[], on="change")
    watch.tick("w")
    ev = watch.tick("w")
    assert ev["event"] == "change"
    assert ev["added_lines"] >= 1 and ev["removed_lines"] >= 1
    assert '"B"' in ev["diff"]
    assert ev["snapshot"] == [{"id": 1, "name": "B"}]


def test_unchanged_tick_stays_quiet(monkeypatch):
    monkeypatch.setattr(watch, "run_command",
                        _capture([_ok([{"id": 1}]), _ok([{"id": 1}])]))
    watch.create("w", ["courses"], interval=30, webhooks=[], headers=[], on="change")
    watch.tick("w")
    assert watch.tick("w")["event"] == "none"


def test_error_result_is_logged_and_loop_survives(monkeypatch):
    monkeypatch.setattr(watch, "run_command", _capture([
        {"ok": False, "error": "not_authenticated", "message": "run scele login"},
    ]))
    watch.create("w", ["courses"], interval=30, webhooks=[], headers=[], on="change")
    ev = watch.tick("w")
    assert ev["event"] == "error" and ev["error"] == "not_authenticated"
    assert watch.events("w")[-1]["event"] == "error"


def test_on_start_emits_first_capture(monkeypatch):
    monkeypatch.setattr(watch, "run_command", _capture([_ok([{"id": 1}])]))
    watch.create("w", ["courses"], interval=30, webhooks=[], headers=[], on="start")
    assert watch.tick("w")["event"] == "start"


# ---------------------------------------------------------------- webhook

def test_webhook_fires_on_change(monkeypatch):
    sent = []

    def _deliver(url, headers, payload, retries=3):
        sent.append((url, headers, payload))
        return {"event": "webhook", "url": url, "status": 200}

    monkeypatch.setattr(watch, "deliver", _deliver)
    monkeypatch.setattr(watch, "run_command",
                        _capture([_ok([{"id": 1}]), _ok([{"id": 2}])]))
    watch.create("w", ["courses"], interval=30,
                 webhooks=["https://hook.example/x"], headers=["X-Tok: abc"], on="change")
    watch.tick("w")
    watch.tick("w")
    assert sent and sent[0][0] == "https://hook.example/x"
    assert sent[0][1] == {"X-Tok": "abc"}
    assert sent[0][2]["event"] == "change"


def test_deliver_retries_then_records_error(monkeypatch):
    calls = []

    def _boom(*_a, **_k):
        calls.append(1)
        raise OSError("nope")

    monkeypatch.setattr(watch.urllib.request, "urlopen", _boom)
    monkeypatch.setattr(watch.time, "sleep", lambda _s: None)
    log = watch.deliver("https://x", {}, {"a": 1}, retries=3)
    assert len(calls) == 3
    assert "error" in log


# ---------------------------------------------------------------- management

def test_listing_and_info(monkeypatch):
    monkeypatch.setattr(watch, "run_command", _capture([_ok([{"id": 1}])]))
    watch.create("alpha", ["courses"], interval=45, webhooks=[], headers=[], on="change")
    watch.tick("alpha")
    _mark_running("alpha")
    rows = watch.listing()
    assert rows[0]["name"] == "alpha" and rows[0]["interval"] == 45
    assert watch.info("alpha")["tick_count"] == 1


def test_listing_prunes_stopped_watches(monkeypatch):
    monkeypatch.setattr(watch, "run_command", _capture([_ok([{"id": 1}])]))
    watch.create("stale", ["courses"], interval=30, webhooks=[], headers=[], on="change")
    watch.tick("stale")
    assert watch.listing() == []
    assert not (config.WATCHES_DIR / "stale").exists()


def test_rename_moves_state(monkeypatch):
    monkeypatch.setattr(watch, "run_command", _capture([_ok([{"id": 1}])]))
    watch.create("old", ["courses"], interval=30, webhooks=[], headers=[], on="change")
    watch.tick("old")
    watch.rename("old", "new")
    assert watch.info("new")["command"] == ["courses"]
    with pytest.raises(watch.WatchError):
        watch.info("old")


def test_remove_deletes_dir(monkeypatch):
    monkeypatch.setattr(watch, "run_command", _capture([_ok([{"id": 1}])]))
    watch.create("gone", ["courses"], interval=30, webhooks=[], headers=[], on="change")
    watch.tick("gone")
    watch.remove("gone")
    assert not (config.WATCHES_DIR / "gone").exists()
    with pytest.raises(watch.WatchError):
        watch.events("gone")


def test_clear_removes_everything(monkeypatch):
    monkeypatch.setattr(watch, "run_command", _capture([_ok([{"id": 1}])]))
    for n in ("a", "b", "c"):
        watch.create(n, ["courses"], interval=30, webhooks=[], headers=[], on="change")
    removed = watch.clear()
    assert sorted(removed) == ["a", "b", "c"]
    assert watch.listing() == []


def test_bad_name_rejected():
    with pytest.raises(watch.WatchError):
        watch.create("bad/name", ["courses"], interval=30, webhooks=[], headers=[], on="change")


@pytest.mark.parametrize("name", [".", ".."])
def test_dot_names_rejected(name):
    with pytest.raises(watch.WatchError):
        watch.create(name, ["courses"], interval=30, webhooks=[], headers=[], on="change")


def test_missing_watch_errors():
    with pytest.raises(watch.WatchError):
        watch.tick("nope")


# ---------------------------------------------------------------- CLI wiring

def test_cli_watch_ls_json(monkeypatch, capsys):
    from click.testing import CliRunner

    from scele.cli import main

    monkeypatch.setattr(watch, "run_command", _capture([_ok([{"id": 1}])]))
    watch.create("c1", ["courses"], interval=30, webhooks=[], headers=[], on="change")
    _mark_running("c1")
    res = CliRunner().invoke(main, ["-c", "watch", "ls"])
    assert res.exit_code == 0
    assert json.loads(res.output)[0]["name"] == "c1"


def test_cli_watch_run_is_alias_safe(monkeypatch):
    from click.testing import CliRunner

    from scele.cli import main

    monkeypatch.setattr(watch, "run_command", _capture([_ok([{"id": 1}]), _ok([{"id": 2}])]))
    watch.create("c2", ["courses"], interval=30, webhooks=[], headers=[], on="change")
    CliRunner().invoke(main, ["-c", "watch", "run", "c2"])
    res = CliRunner().invoke(main, ["-c", "watch", "run", "c2"])
    assert json.loads(res.output)["event"] == "change"
