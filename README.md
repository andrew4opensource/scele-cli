# scele-cli

Command-line client for **SCELE** (`https://scele.cs.ui.ac.id`), the Moodle instance of
Fakultas Ilmu Komputer, Universitas Indonesia.

## Install

### Prebuilt binary — no Python needed (recommended)

**Linux / macOS**

```bash
curl -fsSL https://raw.githubusercontent.com/Andrew4Coding/scele-cli/main/install-bin.sh | sh
```

**Windows** (PowerShell)

```powershell
irm https://raw.githubusercontent.com/Andrew4Coding/scele-cli/main/install-bin.ps1 | iex
```

Fetches the latest release bundle (`scele-<os>-<arch>.tar.gz`) for your OS/arch, verifies
its SHA-256, unpacks it to `~/.local/lib/scele-app`, and links `scele` onto your `PATH`.
Pin a version with `SCELE_VERSION=v0.2.0`; change locations with `SCELE_BIN_DIR` /
`SCELE_APP_DIR`. Or download the archive from the
[Releases page](https://github.com/Andrew4Coding/scele-cli/releases), unpack it, and run
`scele/scele`.

Then open a new terminal:

```bash
scele login
scele courses
```

### With Python (pipx)

```bash
pipx install git+https://github.com/Andrew4Coding/scele-cli.git
```

Or from a clone — the scripts bootstrap pip + pipx for you:

```bash
git clone https://github.com/Andrew4Coding/scele-cli.git && cd scele-cli
./install.sh            # Linux / macOS / WSL / Git-Bash   (flags: --editable, --from, --uninstall)
.\install.ps1           # Windows PowerShell
```

### With npm (global)

```bash
npm install -g scele-cli
```

Installs the `scele` CLI command globally onto your `PATH`. Then run:

```bash
scele login
scele courses
```

Or run directly without installing via `npx`:

```bash
npx scele-cli courses
```

### As an agent skill

```bash
scele skill                                # if scele is installed globally
npx skills add Andrew4Coding/scele-cli     # via vercel-labs/skills
npx scele-cli skill                        # or on-demand via npx
```

See [SKILLS.md](SKILLS.md) and [RELEASING.md](RELEASING.md).

### Shell completion (optional)

```bash
echo 'eval "$(_SCELE_COMPLETE=zsh_source scele)"' >> ~/.zshrc
```

## Usage

```bash
scele login                       # prompts: SCELE username + password (hidden)
scele whoami
scele logout                      # delete the stored token

scele courses                     # courses you are enrolled in
scele course-detail 4234          # category, dates, teachers, summary
scele course 4234                 # section / activity outline
scele people 4234                 # enrolled people + roles
scele grades 4234                 # your grade items
scele course-updates 4234         # what changed recently

scele deadlines --days 14         # upcoming deadlines across ALL courses
scele calendar --days-ahead 30    # calendar events (classes, custom)
scele notifications               # your SCELE notifications

scele categories [--id 31]        # browse the catalog
scele category 31                 # courses in a category

scele forums 4234                 # forums in a course
scele forum 222560                # discussions in a forum (cmid or instance id)
scele thread 62493                # posts in a discussion (nested: parent + depth)
scele post 17474 --subject "..." --message "..." --yes
scele reply 553756 --message "..." --yes

scele assignments 4234            # assignments + due dates + grade info
scele assignment 222043           # your submission status
scele assignment-detail 222043    # instructions + brief attachments
scele submit 55010 --text "my answer" --yes
scele submit 55010 --file ./hw.pdf --yes
scele submit 55010 --text "wip" --draft --yes

scele resources 4234              # downloadable files (with fileurl)
scele download "<pluginfile-url>" -o ./dl
scele download 222038 -o ./dl     # by resource cmid

scele announcements
scele subscribe 17474 [--off]
```

### Interactive TUI

```bash
scele tui          # needs the [tui] extra: pipx inject scele-cli textual
```

### Watch a command for changes

```bash
scele watch deadlines --interval 600 -d              # background; check every 10 min
scele watch assignment 222043 --webhook https://hooks.example/x --webhook-header "X-Token: abc"
scele watch ls                                       # list running watches
scele watch run algo-hw                              # check once now, print the diff
scele watch logs algo-hw
scele watch rename algo-hw algorithms
scele watch rm algorithms                            # stop + delete one
scele watch clear
```

Each check re-runs the command, compares its JSON output, and records a git-style unified
diff of exactly what changed (plus the full new snapshot) — and POSTs it to any configured
webhook. A foreground `scele watch <cmd>` (no `-d`) streams newline-delimited JSON events.
Background watches are POSIX-only and do not survive a reboot. A watch exists only while
running: once it stops it is deleted, and `watch ls` prunes any whose process has gone.

## Config

- Web-service token:
  - Linux/macOS: `$XDG_CONFIG_HOME/scele/` or `~/.config/scele/token.json`
  - Windows: `%APPDATA%\scele\token.json`
  - override the directory with `SCELE_CONFIG_DIR`
- `SCELE_BASE_URL` — point at a different Moodle.
- `SCELE_WS_SERVICE` — web-service short name to mint against (default `moodle_mobile_app`).
- `SCELE_USERNAME` / `SCELE_PASSWORD` — non-interactive `scele login`.

## Layout

```
src/scele/
  cli.py        click command surface
  api.py        high-level operations (one function per command) over the web-service API
  session.py    SceleSession — token holder + ws(wsfunction, **params) caller
  auth.py       terminal login: mint + verify + store a web-service token
  textutil.py   Moodle-HTML → text, epoch → WIB string / countdown
  models.py     dataclasses
  output.py     table / JSON / YAML rendering
  config.py     config-dir + token store
  schema.py     `scele schema` manifest
  watch.py      background command monitoring
```

See `ENDPOINTS.md` for the web-service functions behind each command, `AGENTS.md.bak` for
using `scele` programmatically, and `SKILLS.md` for installing the `scele` **Agent Skill**.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for setup, layout, the output contract, and
the conventions to follow when adding a command.

## License

MIT — see [LICENSE.md](LICENSE.md).
