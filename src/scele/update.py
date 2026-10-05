"""Self-update: reinstall scele at the latest (or a given) GitHub release, using
whichever method it was originally installed with."""

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import requests

from . import __version__
from .session import RequestFailedError

REPO = "Andrew4Coding/scele-cli"
GIT_URL = f"git+https://github.com/{REPO}.git"
RAW = f"https://raw.githubusercontent.com/{REPO}/main"


def normalize_tag(version: str) -> str:
    version = version.strip()
    return version if version.startswith("v") else f"v{version}"


def resolve_tag(version: str | None) -> str:
    if not version or version == "latest":
        try:
            resp = requests.get(f"https://github.com/{REPO}/releases/latest", timeout=15)
        except requests.RequestException as e:
            raise RequestFailedError(f"could not reach GitHub: {e}") from e
        tag = resp.url.rstrip("/").rsplit("/", 1)[-1]
        if resp.status_code != 200 or "/releases/tag/" not in resp.url:
            raise RequestFailedError("could not determine the latest release")
        return tag
    tag = normalize_tag(version)
    try:
        resp = requests.head(f"https://github.com/{REPO}/releases/tag/{tag}",
                             timeout=15, allow_redirects=True)
    except requests.RequestException as e:
        raise RequestFailedError(f"could not reach GitHub: {e}") from e
    if resp.status_code != 200:
        raise RequestFailedError(f"no release named {tag}")
    return tag


def detect_method() -> str:
    if getattr(sys, "frozen", False):
        return "binary"
    pkg = Path(__file__).resolve()
    parts = pkg.parts
    if "node_modules" in parts:
        return "npm"
    if "site-packages" not in parts and "dist-packages" not in parts:
        return "source"
    if "pipx" in Path(sys.prefix).parts:
        return "pipx"
    return "pip"


def _run(cmd: list[str], env: dict | None = None) -> None:
    # Installer chatter goes to stderr so stdout stays a single JSON document.
    try:
        proc = subprocess.run(cmd, stdout=sys.stderr, stderr=sys.stderr,
                              env={**os.environ, **(env or {})})
    except FileNotFoundError as e:
        raise RequestFailedError(f"{cmd[0]} not found on PATH") from e
    if proc.returncode != 0:
        raise RequestFailedError(f"{' '.join(cmd[:3])} ... exited with status {proc.returncode}")


def _fetch_script(name: str, dest: Path) -> Path:
    try:
        resp = requests.get(f"{RAW}/{name}", timeout=30)
        resp.raise_for_status()
    except requests.RequestException as e:
        raise RequestFailedError(f"could not download {name}: {e}") from e
    path = dest / name
    path.write_text(resp.text, encoding="utf-8")
    return path


def _update_binary_posix(tag: str) -> None:
    app_dir = Path(sys.executable).resolve().parent
    env = {"SCELE_VERSION": tag, "SCELE_APP_DIR": str(app_dir)}
    on_path = shutil.which("scele")
    if on_path and Path(on_path).resolve() == Path(sys.executable).resolve():
        env["SCELE_BIN_DIR"] = str(Path(on_path).parent)
    with tempfile.TemporaryDirectory() as tmp:
        _run(["sh", str(_fetch_script("install-bin.sh", Path(tmp)))], env)


def _update_binary_windows(tag: str) -> None:
    # A running scele.exe cannot be overwritten, so hand off to a detached
    # PowerShell that waits for this process to exit before reinstalling.
    app_dir = Path(sys.executable).resolve().parent
    script = (
        f"Wait-Process -Id {os.getpid()} -ErrorAction SilentlyContinue; "
        f"$env:SCELE_VERSION='{tag}'; $env:SCELE_BIN_DIR='{app_dir}'; "
        f"irm {RAW}/install-bin.ps1 | iex"
    )
    subprocess.Popen(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS,
        close_fds=True,
    )


def skill_dirs() -> list[Path]:
    dirs = [Path.home() / ".claude" / "skills" / "scele", Path.cwd() / ".claude" / "skills" / "scele"]
    seen, out = set(), []
    for d in dirs:
        r = d.resolve()
        if r not in seen and (d / "SKILL.md").is_file():
            seen.add(r)
            out.append(d)
    return out


def refresh_skills(tag: str) -> list[str]:
    dirs = skill_dirs()
    if not dirs:
        return []
    try:
        resp = requests.get(f"https://raw.githubusercontent.com/{REPO}/{tag}/skills/scele/SKILL.md", timeout=15)
        resp.raise_for_status()
    except requests.RequestException as e:
        raise RequestFailedError(f"could not download SKILL.md for {tag}: {e}") from e
    changed = []
    for d in dirs:
        target = d / "SKILL.md"
        if target.read_text(encoding="utf-8") != resp.text:
            target.write_text(resp.text, encoding="utf-8")
            changed.append(str(d))
    return changed


def update(version: str | None = None, check: bool = False, force: bool = False) -> dict:
    method = detect_method()
    current = normalize_tag(__version__)
    tag = resolve_tag(version)
    result = {"ok": True, "action": "update", "method": method,
              "current": current, "target": tag, "updated": False}

    if check:
        result["action"] = "check"
        result["update_available"] = tag != current
        return result
    if tag == current and not force:
        _refresh_into(result, tag)
        return result

    if method == "binary":
        if sys.platform == "win32":
            _update_binary_windows(tag)
            result["pending"] = True
        else:
            _update_binary_posix(tag)
    elif method == "pipx":
        _run(["pipx", "install", "--force", f"{GIT_URL}@{tag}"])
    elif method == "pip":
        _run([sys.executable, "-m", "pip", "install", "--upgrade", f"{GIT_URL}@{tag}"])
    elif method == "npm":
        _run(["npm", "install", "-g", f"scele-cli@{tag.lstrip('v')}"])
    else:
        raise RequestFailedError(
            f"scele is running from a source checkout ({Path(__file__).resolve().parents[2]}); "
            f"update it with `git pull` / `git checkout {tag}` instead")

    result["updated"] = True
    _refresh_into(result, tag)
    return result


def _refresh_into(result: dict, tag: str) -> None:
    # The CLI is already updated at this point, so a skill failure is reported, not raised.
    try:
        result["skill_updated"] = refresh_skills(tag)
    except RequestFailedError as e:
        result["skill_updated"] = []
        result["skill_error"] = str(e)
