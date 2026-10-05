import sys

from scele import update


def test_normalize_tag():
    assert update.normalize_tag("0.2.3") == "v0.2.3"
    assert update.normalize_tag("v0.2.3") == "v0.2.3"


def test_detect_binary_when_frozen(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert update.detect_method() == "binary"


def test_check_does_not_install(monkeypatch):
    monkeypatch.setattr(update, "resolve_tag", lambda v: "v9.9.9")
    monkeypatch.setattr(update, "_run", lambda *a, **k: (_ for _ in ()).throw(AssertionError))
    r = update.update(check=True)
    assert r["update_available"] is True and r["updated"] is False


def test_pipx_reinstalls_pinned_tag(monkeypatch):
    calls = []
    monkeypatch.setattr(update, "resolve_tag", lambda v: "v9.9.9")
    monkeypatch.setattr(update, "detect_method", lambda: "pipx")
    monkeypatch.setattr(update, "_run", lambda cmd, env=None: calls.append(cmd))
    monkeypatch.setattr(update, "refresh_skills", lambda tag: [])
    r = update.update("9.9.9")
    assert r["updated"] is True
    assert calls == [["pipx", "install", "--force", f"{update.GIT_URL}@v9.9.9"]]


class _Resp:
    text = "new skill"

    def raise_for_status(self):
        pass


def test_refresh_skills_only_touches_installed_and_changed(monkeypatch, tmp_path):
    home, cwd = tmp_path / "home", tmp_path / "proj"
    user_skill = home / ".claude" / "skills" / "scele"
    user_skill.mkdir(parents=True)
    (user_skill / "SKILL.md").write_text("old skill")
    cwd.mkdir()
    monkeypatch.setattr(update.Path, "home", lambda: home)
    monkeypatch.chdir(cwd)
    monkeypatch.setattr(update.requests, "get", lambda *a, **k: _Resp())

    assert update.refresh_skills("v9.9.9") == [str(user_skill)]
    assert (user_skill / "SKILL.md").read_text() == "new skill"
    assert not (cwd / ".claude").exists()
    assert update.refresh_skills("v9.9.9") == []
