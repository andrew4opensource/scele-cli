"""`scele` command-line entry point. Every command prints one JSON document to stdout."""

import sys
from pathlib import Path

import click

from . import __version__, api, watch as _watch
from .auth import terminal_login
from .config import base_url, clear_auth, token_status
from .output import emit, fail
from .session import NotAuthenticatedError, RequestFailedError, SceleSession


def _session(ctx) -> SceleSession:
    if ctx.obj.get("session") is None:
        ctx.obj["session"] = SceleSession()
    return ctx.obj["session"]


def _out(ctx, obj):
    emit(obj, fmt=ctx.obj["format"], compact=ctx.obj["compact"])


def _guard(fn):
    try:
        return fn()
    except NotAuthenticatedError as e:
        fail(str(e), code="not_authenticated")
    except _watch.WatchError as e:
        fail(str(e), code="watch_not_found")
    except RequestFailedError as e:
        fail(str(e), code="request_failed")
    except Exception as e:  # noqa: BLE001 - surface any failure as JSON
        fail(f"{type(e).__name__}: {e}", code="request_failed")


class _WatchGroup(click.Group):
    """A group that treats `scele watch <cmd> ...` as `scele watch start <cmd> ...`
    whenever the first token is not one of its own subcommands."""

    def resolve_command(self, ctx, args):
        if args and args[0] not in self.commands and not args[0].startswith("-"):
            args = ["start", *args]
        return super().resolve_command(ctx, args)


@click.group(
    context_settings={"help_option_names": ["-h", "--help"]},
    epilog="Output format defaults to a table on a terminal, plain JSON when piped. "
           "Use `-f json`, `-f yaml`, or `-f table` to override. "
           "Run `scele schema` for a machine-readable manifest. "
           "Run `scele skill` to install the AI agent skill.",
)
@click.version_option(__version__, prog_name="scele", message="%(version)s")
@click.option("-c", "--compact", is_flag=True, help="Single-line JSON (implies -f json).")
@click.option("-f", "--format", "fmt",
              type=click.Choice(["auto", "json", "yaml", "table"]),
              default="auto", show_default=True,
              help="Output format. auto = table on terminal, JSON when piped.")
@click.pass_context
def main(ctx, compact, fmt):
    """Command-line client for SCELE (Moodle) at Fasilkom UI."""
    ctx.obj = {"compact": compact, "format": fmt, "session": None}


@main.command()
@click.pass_context
def schema(ctx):
    """Print a machine-readable manifest of all commands and I/O shapes."""
    from .schema import build
    emit(build(main), fmt="json", compact=ctx.obj["compact"])


@main.command()
@click.option("-p", "--project", is_flag=True, help="Install to repository scope (.claude/skills/scele/).")
@click.option("--dir", "custom_dir", type=click.Path(), help="Install to a custom directory (<path>/scele/).")
@click.option("--uninstall", is_flag=True, help="Remove the installed skill.")
@click.pass_context
def skill(ctx, project, custom_dir, uninstall):
    """Install or manage the scele agent skill for Claude Code and AI agents."""
    import shutil

    if custom_dir:
        dest = Path(custom_dir).resolve() / "scele"
        scope = "custom"
    elif project:
        dest = Path.cwd() / ".claude" / "skills" / "scele"
        scope = "project"
    else:
        dest = Path.home() / ".claude" / "skills" / "scele"
        scope = "user"

    if uninstall:
        if dest.exists():
            shutil.rmtree(dest)
        _out(ctx, {"ok": True, "action": "uninstall", "path": str(dest), "scope": scope})
        return

    # Find SKILL.md
    pkg_root = Path(__file__).resolve().parents[2]
    skill_src = pkg_root / "skills" / "scele"
    if not (skill_src / "SKILL.md").exists():
        skill_src = Path(__file__).resolve().parent / "skills" / "scele"

    if (skill_src / "SKILL.md").exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(skill_src, dest)
    else:
        dest.mkdir(parents=True, exist_ok=True)
        import requests
        url = "https://raw.githubusercontent.com/Andrew4Coding/scele-cli/main/skills/scele/SKILL.md"
        resp = requests.get(url, timeout=10)
        if resp.status_code == 200:
            (dest / "SKILL.md").write_text(resp.text, encoding="utf-8")
        else:
            fail(f"Could not locate skill source (HTTP {resp.status_code})", code="request_failed")

    _out(ctx, {"ok": True, "action": "install", "path": str(dest), "scope": scope})


@main.command()
@click.option("-u", "--username", help="SCELE username (else prompted, or $SCELE_USERNAME).")
@click.option("-p", "--password", help="SCELE password (else prompted, or $SCELE_PASSWORD). "
                                       "Avoid on the command line; prefer the prompt or env var.")
@click.pass_context
def login(ctx, username, password):
    """Log in with your SCELE username and password and store a web-service token."""
    code = terminal_login(username, password)
    _out(ctx, {"ok": code == 0, "action": "login"})


@main.command()
@click.pass_context
def logout(ctx):
    """Delete the stored web-service token."""
    clear_auth()
    _out(ctx, {"ok": True, "action": "logout"})


@main.command()
@click.pass_context
def whoami(ctx):
    """Report whether the stored token is valid and who it belongs to."""
    s = _session(ctx)
    store = token_status()
    if s.is_authenticated():
        info = s.site_info()
        _out(ctx, {"ok": True, "authenticated": True, "base_url": base_url(),
                   "user": info.get("fullname"), "userid": info.get("userid"),
                   "username": info.get("username"), "token": store})
    else:
        fail("not authenticated; run `scele login`", code="not_authenticated")


@main.command()
@click.pass_context
def courses(ctx):
    """List the courses on your dashboard."""
    s = _session(ctx)
    _out(ctx, _guard(lambda: api.my_courses(s)))


@main.command()
@click.option("--id", "category_id", help="Parent category id to list children of.")
@click.pass_context
def categories(ctx, category_id):
    """Browse the course category tree."""
    s = _session(ctx)
    _out(ctx, _guard(lambda: api.categories(s, category_id)))


@main.command("category")
@click.argument("category_id")
@click.pass_context
def category_courses(ctx, category_id):
    """List courses inside a category."""
    s = _session(ctx)
    _out(ctx, _guard(lambda: api.courses_in_category(s, category_id)))


@main.command()
@click.argument("course_id")
@click.pass_context
def course(ctx, course_id):
    """Show a course outline (sections and activities)."""
    s = _session(ctx)
    _out(ctx, _guard(lambda: api.course(s, course_id)))


@main.command("course-detail")
@click.argument("course_id")
@click.pass_context
def course_detail(ctx, course_id):
    """Show course metadata: category, dates, teachers, summary."""
    s = _session(ctx)
    _out(ctx, _guard(lambda: api.course_detail(s, course_id)))


@main.command()
@click.argument("course_id")
@click.pass_context
def people(ctx, course_id):
    """List the people enrolled in a course."""
    s = _session(ctx)
    _out(ctx, _guard(lambda: api.people(s, course_id)))


@main.command()
@click.argument("course_id")
@click.pass_context
def grades(ctx, course_id):
    """Show your grade items for a course."""
    s = _session(ctx)
    _out(ctx, _guard(lambda: api.grades(s, course_id)))


@main.command("course-updates")
@click.argument("course_id")
@click.option("--since-days", default=7, show_default=True, help="Look back this many days.")
@click.pass_context
def course_updates(ctx, course_id, since_days):
    """Show what changed in a course recently."""
    s = _session(ctx)
    _out(ctx, _guard(lambda: api.course_updates(s, course_id, since_days)))


@main.command()
@click.option("--days", default=14, show_default=True, help="Look-ahead window in days.")
@click.option("--limit", default=25, show_default=True, help="Max events to return.")
@click.pass_context
def deadlines(ctx, days, limit):
    """List upcoming deadlines across all your courses."""
    s = _session(ctx)
    _out(ctx, _guard(lambda: api.deadlines(s, days, limit)))


@main.command()
@click.option("--days-back", default=7, show_default=True)
@click.option("--days-ahead", default=30, show_default=True)
@click.pass_context
def calendar(ctx, days_back, days_ahead):
    """List calendar events (classes, custom events, deadlines)."""
    s = _session(ctx)
    _out(ctx, _guard(lambda: api.calendar(s, days_back, days_ahead)))


@main.command()
@click.option("--limit", default=20, show_default=True, help="Max notifications to return.")
@click.pass_context
def notifications(ctx, limit):
    """Show your recent SCELE notifications."""
    s = _session(ctx)
    _out(ctx, _guard(lambda: api.notifications(s, limit)))


@main.command()
@click.argument("course_id")
@click.pass_context
def forums(ctx, course_id):
    """List the forums in a course."""
    s = _session(ctx)
    _out(ctx, _guard(lambda: api.forums(s, course_id)))


@main.command()
@click.argument("forum_id")
@click.option("--limit", default=50, show_default=True, help="Max discussions to return.")
@click.pass_context
def forum(ctx, forum_id, limit):
    """List discussions in a forum."""
    s = _session(ctx)
    _out(ctx, _guard(lambda: api.forum(s, forum_id, limit)))


@main.command()
@click.argument("discussion_id")
@click.pass_context
def thread(ctx, discussion_id):
    """Show the posts in a discussion thread."""
    s = _session(ctx)
    _out(ctx, _guard(lambda: api.thread(s, discussion_id)))


@main.command()
@click.argument("course_id")
@click.pass_context
def assignments(ctx, course_id):
    """List assignments in a course."""
    s = _session(ctx)
    _out(ctx, _guard(lambda: api.assignments(s, course_id)))


@main.command()
@click.argument("cmid")
@click.pass_context
def assignment(ctx, cmid):
    """Show an assignment's submission status."""
    s = _session(ctx)
    _out(ctx, _guard(lambda: api.assignment(s, cmid)))


@main.command("assignment-detail")
@click.argument("ref")
@click.pass_context
def assignment_detail(ctx, ref):
    """Show an assignment's instructions, due dates and brief attachments (id or cmid)."""
    s = _session(ctx)
    _out(ctx, _guard(lambda: api.assignment_detail(s, ref)))


@main.command()
@click.argument("ref")
@click.option("--text", help="Online-text submission body.")
@click.option("--file", "file_path", type=click.Path(exists=True, dir_okay=False),
              help="Local file to upload as the submission.")
@click.option("--draft", is_flag=True, help="Save as a draft; do not submit for grading.")
@click.option("--yes", is_flag=True, help="Skip the confirmation prompt.")
@click.pass_context
def submit(ctx, ref, text, file_path, draft, yes):
    """Submit online text or a file to an assignment (id or cmid)."""
    if bool(text) == bool(file_path):
        fail("pass exactly one of --text or --file", code="request_failed")
    what = "text" if text else f"file {file_path}"
    final = not draft
    if not yes:
        verb = "submit for grading" if final else "save as draft"
        click.confirm(f"{verb.capitalize()}: {what} -> assignment {ref}?", abort=True, err=True)
    s = _session(ctx)
    if text:
        res = _guard(lambda: api.submit_text(s, ref, text, final))
    else:
        res = _guard(lambda: api.submit_file(s, ref, file_path, final))
    _out(ctx, {"action": "submit", **res})


@main.command()
@click.argument("course_id")
@click.pass_context
def resources(ctx, course_id):
    """List downloadable file/folder resources in a course."""
    s = _session(ctx)
    _out(ctx, _guard(lambda: api.resources(s, course_id)))


@main.command()
@click.pass_context
def announcements(ctx):
    """Show front-page / dashboard announcements."""
    s = _session(ctx)
    _out(ctx, _guard(lambda: api.announcements(s)))


@main.command()
@click.argument("course_id")
@click.option("--instance", default=None, help="Self-enrol instance id (optional).")
@click.option("--key", default="", help="Enrolment key, if the course requires one.")
@click.pass_context
def enrol(ctx, course_id, instance, key):
    """Self-enrol into a course."""
    s = _session(ctx)
    ok = _guard(lambda: api.enrol(s, course_id, instance, key))
    _out(ctx, {"ok": bool(ok), "action": "enrol", "course_id": course_id, "verified": bool(ok)})


@main.command()
@click.argument("forum_id")
@click.option("--off", is_flag=True, help="Unsubscribe instead of subscribe.")
@click.pass_context
def subscribe(ctx, forum_id, off):
    """Subscribe to (or, with --off, unsubscribe from) a forum."""
    s = _session(ctx)
    ok = _guard(lambda: api.forum_subscribe(s, forum_id, state=not off))
    _out(ctx, {"ok": bool(ok), "action": "subscribe",
               "forum_id": forum_id, "subscribed": not off})


@main.command()
@click.argument("forum_id")
@click.option("--subject", required=True)
@click.option("--message", required=True)
@click.option("--yes", is_flag=True, help="Skip the confirmation prompt.")
@click.pass_context
def post(ctx, forum_id, subject, message, yes):
    """Start a new discussion in a forum."""
    if not yes:
        click.confirm("Post this new discussion to the forum?", abort=True, err=True)
    s = _session(ctx)
    url = _guard(lambda: api.forum_post(s, forum_id, subject, message))
    _out(ctx, {"ok": True, "action": "post", "forum_id": forum_id, "url": url})


@main.command()
@click.argument("post_id")
@click.option("--message", required=True)
@click.option("--subject", default="", help="Override the auto 'Re:' subject.")
@click.option("--yes", is_flag=True, help="Skip the confirmation prompt.")
@click.pass_context
def reply(ctx, post_id, message, subject, yes):
    """Reply to a forum post."""
    if not yes:
        click.confirm("Post this reply?", abort=True, err=True)
    s = _session(ctx)
    url = _guard(lambda: api.forum_reply(s, post_id, message, subject))
    _out(ctx, {"ok": True, "action": "reply", "post_id": post_id, "url": url})


@main.command()
@click.argument("target")
@click.option("-o", "--out-dir", default=".", type=click.Path(file_okay=False), help="Output dir.")
@click.pass_context
def download(ctx, target, out_dir):
    """Download a resource cmid or a pluginfile URL."""
    s = _session(ctx)
    dest = _guard(lambda: api.download(s, target, Path(out_dir)))
    _out(ctx, {"ok": True, "action": "download", "path": str(dest)})


@main.command()
def tui():
    """Launch the interactive TUI.

    Requires the 'tui' extra: pip install scele-cli[tui]
    """
    try:
        from .tui.app import SceleApp
    except ImportError:
        raise click.ClickException(
            "The TUI requires the 'textual' package.\n"
            "Install it with:  pip install scele-cli[tui]\n"
            "Or with pipx:     pipx inject scele-cli textual"
        )
    app = SceleApp()
    app.run()


@main.group("watch", cls=_WatchGroup,
            context_settings={"help_option_names": ["-h", "--help"]})
def watch():
    """Re-run a command on an interval and report exact line-level output changes.

    `scele watch <command...>` starts a watch; `ls`, `rm`, `rename`, `logs`, and
    `run` manage existing ones. Foreground watches stream newline-delimited JSON
    events (the one command that is not single-document).
    """


@watch.command("start", context_settings={"ignore_unknown_options": True})
@click.argument("command", nargs=-1, required=True)
@click.option("--name", help="Watch name (default: derived from the command).")
@click.option("--interval", default=_watch.DEFAULT_INTERVAL, show_default=True,
              help=f"Seconds between checks (min {_watch.MIN_INTERVAL}).")
@click.option("--webhook", "webhooks", multiple=True, help="Webhook URL to POST changes to (repeatable).")
@click.option("--webhook-header", "headers", multiple=True,
              help="Header for webhook requests, 'Key: Value' (repeatable).")
@click.option("--on", type=click.Choice(["start", "change"]), default="change", show_default=True,
              help="Fire the webhook on the first capture too, or only on later changes.")
@click.option("-d", "--detach", is_flag=True, help="Run in the background.")
@click.pass_context
def watch_start(ctx, command, name, interval, webhooks, headers, on, detach):
    """Start watching COMMAND (any scele subcommand with its arguments)."""
    wname = name or "-".join(command) or "watch"
    cfg = _guard(lambda: _watch.create(
        wname, list(command), interval=interval,
        webhooks=list(webhooks), headers=list(headers), on=on))
    if detach:
        spawned = _guard(lambda: _watch.spawn(wname))
        _out(ctx, {"ok": True, "action": "watch", "name": wname, "detached": True,
                   "pid": spawned["pid"], "command": list(command), "interval": cfg["interval"]})
        return
    click.echo(f"watching '{wname}' every {cfg['interval']}s; Ctrl-C to stop", err=True)
    _guard(lambda: _watch.run_loop(wname, stream=sys.stdout))


@watch.command("_run", hidden=True)
@click.argument("name")
def watch_run_daemon(name):
    """Internal: execute the blocking watch loop (used by --detach)."""
    _watch.run_loop(name)


@watch.command("ls")
@click.pass_context
def watch_ls(ctx):
    """List running watches (stopped ones are pruned)."""
    _out(ctx, _guard(_watch.listing))


@watch.command("run")
@click.argument("name")
@click.pass_context
def watch_run(ctx, name):
    """Check a watch once now and print the diff."""
    _out(ctx, _guard(lambda: _watch.tick(name)))


@watch.command("rm")
@click.argument("name")
@click.pass_context
def watch_rm(ctx, name):
    """Stop and delete a watch."""
    signalled = _guard(lambda: _watch.remove(name))
    _out(ctx, {"ok": True, "action": "watch-rm", "name": name, "stopped": bool(signalled)})


@watch.command("clear")
@click.pass_context
def watch_clear(ctx):
    """Stop and delete every watch."""
    names = _guard(_watch.clear)
    _out(ctx, {"ok": True, "action": "watch-clear", "removed": names})


@watch.command("rename")
@click.argument("name")
@click.argument("new_name")
@click.pass_context
def watch_rename(ctx, name, new_name):
    """Rename a stopped watch."""
    _guard(lambda: _watch.rename(name, new_name))
    _out(ctx, {"ok": True, "action": "watch-rename", "name": name, "new_name": new_name})


@watch.command("logs")
@click.argument("name")
@click.option("--limit", default=50, show_default=True, help="Number of events to show.")
@click.pass_context
def watch_logs(ctx, name, limit):
    """Show a watch's recorded events."""
    _out(ctx, _guard(lambda: _watch.events(name, limit)))


if __name__ == "__main__":
    main()
