# Releasing

## Cut a release

```bash
chmod +x scripts/*.sh          # first time
scripts/release.sh 0.2.0       # bumps src/scele/__init__.py + package.json, commits "release: v0.2.0"
git push origin main
```

Every push to `main` runs `.github/workflows/release.yml`. The `check` job reads
`__version__` from `src/scele/__init__.py`; if no `v<version>` tag exists yet it:

1. builds the `scele` **onedir bundle** on 4 runners
   (`linux-x86_64`, `linux-aarch64`, `macos-arm64`, `windows-x86_64` — GitHub has
   no Intel-mac runner any more; Intel-mac users install via `pipx`),
2. packs each `dist/scele/` as `scele-<target>.tar.gz` (`.zip` on Windows),
3. builds the Python `sdist` + `wheel`,
4. pushes the `v<version>` tag,
5. creates the GitHub Release with every archive, `checksums.txt`, and auto-generated notes.

Pushes that don't change `__version__` are a no-op (the tag already exists).
To rebuild an already-released version, run **Actions → Release → Run workflow**
with **force** checked.

> The bundle is **onedir**, not onefile: a onefile binary re-extracts its whole
> archive to a temp dir on every run (multiple seconds); onedir starts in ~0.1s.
> `install-bin.sh` / `install-bin.ps1` unpack the archive to
> `~/.local/lib/scele-app` (or `%LOCALAPPDATA%\Programs\scele`) and link
> `scele` onto `PATH`.

## Version source

`src/scele/__init__.py` `__version__` is the single source. `pyproject.toml` reads it via
`[tool.hatch.version]`; `scele schema` and `scele --version` report it.

## Build a binary locally

```bash
pip install -e ".[build]"        # add ".[build,tui]" to bundle the `scele tui` UI
scripts/build-binary.sh          # -> dist/scele/  (this OS/arch only; no cross-compile)
tar -czf scele-macos-arm64.tar.gz -C dist scele   # what the workflow ships
```

## What users run

| method | command | needs |
|---|---|---|
| binary (raw script) | `curl -fsSL https://raw.githubusercontent.com/Andrew4Coding/scele-cli/main/install-bin.sh \| sh` | nothing |
| binary (manual) | download `scele-<os>-<arch>.tar.gz`, unpack, run `scele/scele` (link it onto `PATH`) | nothing |
| Python | `pipx install git+https://github.com/Andrew4Coding/scele-cli.git` | Python 3.10+, pipx |
| from clone | `./install.sh` / `.\install.ps1` | Python 3.10+ |
| npm (global) | `npm install -g scele-cli` (or `npx scele-cli`) | node >= 16 |
| agent skill | `npx skills add Andrew4Coding/scele-cli` | node |

The `install-bin.sh` / `install-bin.ps1` scripts always fetch the **latest** release unless
`SCELE_VERSION` is set, so they keep working across releases without edits.

## Checklist

- [ ] `pytest -q` green, `scele schema` runs
- [ ] `README.md` / `AGENTS.md` / `skills/scele/SKILL.md` reflect any command changes
- [ ] `scripts/release.sh <version>` → `git push origin main`
- [ ] Release workflow green; assets present on the Release page
- [ ] `curl … install-bin.sh | sh` on a clean machine installs and runs
