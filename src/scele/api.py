"""High-level SCELE operations, one function per CLI command, over the Moodle
web-service API. Every function takes a :class:`SceleSession`.
"""

import os
import time
from collections.abc import Callable
from pathlib import Path

from .models import (
    Activity, Announcement, AssignmentInfo, AssignmentStatus, CalendarEvent, Category,
    Course, CourseDetail, Deadline, Discussion, Grade, Notification, Person, Post,
    Resource, Section,
)
from .session import RequestFailedError, SceleSession
from .textutil import clean_html, until, wib

_FILE_MODS = {"resource", "folder", "url"}


# ---------------------------------------------------------------- helpers

def _course_module(s: SceleSession, cmid: str) -> dict:
    """Resolve an activity cmid to its {id, instance, course, modname, name, url}."""
    data = s.ws("core_course_get_course_module", cmid=int(cmid))
    cm = (data or {}).get("cm") or {}
    if not cm:
        raise RequestFailedError(f"course module {cmid} not found")
    return cm


def _discussion_url(s: SceleSession, discussion_id) -> str:
    return f"{s.base}/mod/forum/discuss.php?d={discussion_id}"


def _forum_instance_id(s: SceleSession, forum_id: int) -> int:
    """Accept either a forum instance id or an activity cmid; return the instance id.

    `forums` / `course` hand out the activity cmid; `mod_forum_get_forum_discussions`
    only accepts the forum's own instance id.
    """
    try:
        cm = s.ws("core_course_get_course_module", cmid=forum_id) or {}
        inst = (cm.get("cm") or {}).get("instance")
        if inst and (cm.get("cm") or {}).get("modname") == "forum":
            return int(inst)
    except RequestFailedError:
        pass
    return forum_id


def _discussions_for(s: SceleSession, fid: int, perpage: int) -> list[dict] | None:
    """One forum id → its discussions, or None if SCELE rejects the id."""
    for fn, extra in (
        ("mod_forum_get_forum_discussions", {"sortorder": 1}),
        ("mod_forum_get_forum_discussions_paginated",
         {"sortby": "timemodified", "sortdirection": "DESC"}),
    ):
        try:
            data = s.ws(fn, forumid=fid, page=0, perpage=perpage, **extra) or {}
        except RequestFailedError:
            continue
        return data.get("discussions") or []
    return None


def _forum_discussions(s: SceleSession, forum_id: int, perpage: int = 50) -> list[dict]:
    """Discussions in a forum, accepting a forum instance id or an activity cmid."""
    got = _discussions_for(s, forum_id, perpage)
    if got is not None:
        return got
    instance = _forum_instance_id(s, forum_id)
    if instance != forum_id:
        got = _discussions_for(s, instance, perpage)
    return got or []


def _news_forum_id(s: SceleSession) -> str | None:
    forums = s.ws("mod_forum_get_forums_by_courses", courseids=[1]) or []
    for f in forums:
        if f.get("type") == "news":
            return str(f.get("id"))
    return str(forums[0]["id"]) if forums else None


# ---------------------------------------------------------------- courses

def my_courses(s: SceleSession) -> list[Course]:
    """Return the courses the user is enrolled in."""
    data = s.ws("core_enrol_get_users_courses", userid=s.userid()) or []
    out = [
        Course(
            id=str(c.get("id")),
            name=clean_html(c.get("fullname") or c.get("shortname")),
            url=f"{s.base}/course/view.php?id={c.get('id')}",
            shortname=c.get("shortname") or "",
            category=str(c.get("category") or ""),
            progress=round(c["progress"], 1) if isinstance(c.get("progress"), (int, float)) else None,
        )
        for c in data if not c.get("hidden")
    ]
    out.sort(key=lambda c: c.shortname.lower())
    return out


def course_detail(s: SceleSession, course_id: str) -> CourseDetail:
    """Return metadata for one course: category, dates, teachers, summary."""
    found = s.ws("core_course_get_courses_by_field", field="id", value=int(course_id)) or {}
    courses = found.get("courses") or []
    if not courses:
        raise RequestFailedError(f"course {course_id} not found")
    c = courses[0]
    teachers = [
        {"id": str(t.get("id")), "name": clean_html(t.get("fullname"))}
        for t in (c.get("contacts") or [])
    ]
    return CourseDetail(
        id=str(c.get("id")),
        shortname=c.get("shortname") or "",
        fullname=clean_html(c.get("fullname")),
        category=clean_html(c.get("categoryname")) or str(c.get("categoryid") or ""),
        summary=clean_html(c.get("summary"), 1200),
        start=wib(c.get("startdate")),
        end=wib(c.get("enddate")),
        teachers=teachers[:20],
    )


def categories(s: SceleSession, category_id: str | None = None) -> list[Category]:
    """Return course categories, optionally the children of one parent."""
    crit = [{"key": "parent", "value": int(category_id)}] if category_id else []
    data = s.ws("core_course_get_categories", criteria=crit) or []
    return [
        Category(
            id=str(c.get("id")),
            name=clean_html(c.get("name")),
            url=f"{s.base}/course/index.php?categoryid={c.get('id')}",
            course_count=c.get("coursecount"),
        )
        for c in data
    ]


def courses_in_category(s: SceleSession, category_id: str) -> list[Course]:
    """Return the courses listed under a category."""
    data = s.ws("core_course_get_courses_by_field", field="category", value=int(category_id)) or {}
    return [
        Course(
            id=str(c.get("id")),
            name=clean_html(c.get("fullname")),
            url=f"{s.base}/course/view.php?id={c.get('id')}",
            shortname=c.get("shortname") or "",
            category=str(category_id),
        )
        for c in (data.get("courses") or [])
    ]


def course(s: SceleSession, course_id: str) -> list[Section]:
    """Return the section/activity outline of a course."""
    data = s.course_contents(course_id)
    out: list[Section] = []
    for sec in data:
        acts = [
            Activity(
                cmid=str(m.get("id")),
                type=m.get("modname") or "",
                name=clean_html(m.get("name")),
                url=m.get("url") or "",
                section=clean_html(sec.get("name")),
            )
            for m in (sec.get("modules") or [])
        ]
        out.append(Section(
            name=clean_html(sec.get("name")),
            summary=clean_html(sec.get("summary"), 600),
            activities=acts,
        ))
    return out


def _activities(s: SceleSession, course_id: str, modtype: str) -> list[Activity]:
    return [a for sec in course(s, course_id) for a in sec.activities if a.type == modtype]


def forums(s: SceleSession, course_id: str) -> list[Activity]:
    """Return the forums in a course. ``cmid`` is the activity id, as in ``course``."""
    data = s.ws("mod_forum_get_forums_by_courses", courseids=[int(course_id)]) or []
    return [
        Activity(
            cmid=str(f.get("cmid") or f.get("id")),
            type=f.get("type") or "forum",
            name=clean_html(f.get("name")) or "",
            url=f"{s.base}/mod/forum/view.php?id={f.get('cmid') or f.get('id')}",
            section=str(f.get("section") or ""),
        )
        for f in data
    ]


def resources(s: SceleSession, course_id: str) -> list[Resource]:
    """Return downloadable file/folder/url resources in a course."""
    data = s.course_contents(course_id)
    out: list[Resource] = []
    for sec in data:
        for m in (sec.get("modules") or []):
            if m.get("modname") not in _FILE_MODS:
                continue
            files = m.get("contents") or []
            if not files:
                out.append(Resource(cmid=str(m.get("id")), name=clean_html(m.get("name")),
                                    type=m.get("modname") or "", section=clean_html(sec.get("name"))))
            for f in files:
                out.append(Resource(
                    cmid=str(m.get("id")),
                    name=clean_html(m.get("name") or f.get("filename")),
                    type=m.get("modname") or "",
                    fileurl=f.get("fileurl") or "",
                    filename=f.get("filename") or "",
                    filesize=f.get("filesize"),
                    section=clean_html(sec.get("name")),
                ))
    return out


def assignments(s: SceleSession, course_id: str) -> list[AssignmentInfo]:
    """Return assignments in a course with due dates and grade info."""
    data = s.ws("mod_assign_get_assignments", courseids=[int(course_id)]) or {}
    out: list[AssignmentInfo] = []
    for c in data.get("courses") or []:
        for a in c.get("assignments") or []:
            out.append(_assignment_info(s, a))
    out.sort(key=lambda a: a.due or "9999")
    return out


def _assignment_info(s: SceleSession, a: dict) -> AssignmentInfo:
    cutoff = a.get("cutoffdate") or 0
    due = a.get("duedate") or 0
    return AssignmentInfo(
        id=str(a.get("id")),
        cmid=str(a.get("cmid")),
        course_id=str(a.get("course")),
        name=clean_html(a.get("name")),
        due=wib(due),
        due_in=until(due),
        cutoff=wib(cutoff),
        allow_late=bool(cutoff and due and cutoff > due),
        grade=str(a.get("grade")) if a.get("grade") is not None else "",
        instructions=clean_html(a.get("intro"), 4000),
        team_submission=bool(a.get("teamsubmission")),
        max_attempts=a.get("maxattempts"),
        attachments=[
            {"filename": f.get("filename"), "filesize": f.get("filesize"),
             "fileurl": f.get("fileurl")}
            for f in (a.get("introattachments") or [])
        ],
    )


def assignment_detail(s: SceleSession, ref: str) -> AssignmentInfo:
    """Full detail for one assignment, found by instance id OR cmid."""
    want = int(ref)
    ids = [int(c.id) for c in my_courses(s)]
    data = s.ws("mod_assign_get_assignments", courseids=ids) or {}
    for cc in data.get("courses") or []:
        for a in cc.get("assignments") or []:
            if a.get("id") == want or a.get("cmid") == want:
                return _assignment_info(s, a)
    raise RequestFailedError(f"assignment {ref} not found in your courses")


def forum(s: SceleSession, forum_id: str, limit: int = 50) -> list[Discussion]:
    """Return the discussion list of a forum (id = forum instance id)."""
    out = []
    for d in _forum_discussions(s, int(forum_id), limit):
        did = d.get("discussion") or d.get("id")
        out.append(Discussion(
            id=str(did),
            name=clean_html(d.get("name") or d.get("subject")),
            url=_discussion_url(s, did),
            author=d.get("userfullname") or "",
            replies=d.get("numreplies"),
            unread=d.get("numunread"),
            created=wib(d.get("created")),
            last_post=wib(d.get("timemodified")),
        ))
    return out


def thread(s: SceleSession, discussion_id: str) -> list[Post]:
    """Return the posts in a discussion thread, nested (parent + depth)."""
    data = s.ws("mod_forum_get_discussion_posts", discussionid=int(discussion_id),
                sortby="created", sortdirection="ASC") or {}
    raw = data.get("posts") or data.get("messages") or []
    out: list[Post] = []
    for p in raw:
        author = p.get("author") if isinstance(p.get("author"), dict) else None
        parent = p.get("parentid") if p.get("parentid") is not None else p.get("parent")
        out.append(Post(
            id=str(p.get("id")),
            author=(author.get("fullname") if author else p.get("userfullname")) or "",
            created=wib(p.get("timecreated") or p.get("created")),
            subject=clean_html(p.get("subject")),
            body=clean_html((p.get("message") if isinstance(p.get("message"), str)
                             else (p.get("message") or {}).get("text")) or ""),
            parent=str(parent) if parent else "",
        ))
    by_id = {p.id: p for p in out}
    for p in out:
        depth, cur = 0, p.parent
        while cur and cur in by_id and depth < len(out):
            depth += 1
            cur = by_id[cur].parent
        p.depth = depth
    return out


def assignment(s: SceleSession, cmid: str) -> AssignmentStatus:
    """Return the user's submission status for an assignment (by cmid)."""
    cm = _course_module(s, cmid)
    assignid = int(cm.get("instance"))
    status = s.ws("mod_assign_get_submission_status", assignid=assignid,
                  userid=s.userid()) or {}
    last = status.get("lastattempt") or {}
    sub = last.get("teamsubmission") or last.get("submission") or {}
    files, onlinetext = [], ""
    for plug in sub.get("plugins") or []:
        for area in plug.get("fileareas") or []:
            for f in area.get("files") or []:
                if f.get("fileurl"):
                    files.append({"name": f.get("filename") or "", "url": f.get("fileurl")})
        for ef in plug.get("editorfields") or []:
            if ef.get("name") == "onlinetext":
                onlinetext = clean_html(ef.get("text"), 2000)
    raw = sub.get("status")
    state = {
        "submitted": "SUBMITTED", "submitted_for_grading": "SUBMITTED",
        "draft": "draft", "reopened": "reopened",
    }.get(raw, ("not opened" if raw is None else str(raw)))
    if raw == "new":
        state = "draft" if (files or onlinetext) else "opened, not submitted"
    fields = {
        "Submission status": state,
        "Grading status": last.get("gradingstatus") or "",
        "Team submission": "yes" if last.get("teamsubmission") else "no",
        "Attempt number": str(sub.get("attemptnumber") if sub.get("attemptnumber") is not None else ""),
        "Last modified": wib(sub.get("timemodified")),
    }
    if onlinetext:
        fields["Online text"] = onlinetext
    return AssignmentStatus(cmid=str(cmid), name=clean_html(cm.get("name")),
                            fields={k: v for k, v in fields.items() if v}, files=files)


def announcements(s: SceleSession) -> list[Announcement]:
    """Return the site-news announcements from the front page."""
    fid = _news_forum_id(s)
    if not fid:
        return []
    out = []
    for d in _forum_discussions(s, int(fid), 25):
        did = d.get("discussion") or d.get("id")
        out.append(Announcement(
            subject=clean_html(d.get("name") or d.get("subject")),
            author=d.get("userfullname") or "",
            date=wib(d.get("created")),
            body=clean_html(d.get("message"), 4000),
            permalink=_discussion_url(s, did),
        ))
    return out


# ---------------------------------------------------------------- grades / calendar / people

def grades(s: SceleSession, course_id: str) -> list[Grade]:
    """Return the user's grade items for a course."""
    data = s.ws("gradereport_user_get_grade_items", courseid=int(course_id),
                userid=s.userid()) or {}
    out = []
    for u in data.get("usergrades") or []:
        for item in u.get("gradeitems") or []:
            rng = ""
            if item.get("grademin") is not None and item.get("grademax") is not None:
                rng = f"{item['grademin']:g}–{item['grademax']:g}"
            out.append(Grade(
                item=clean_html(item.get("itemname")) or item.get("itemtype") or "(item)",
                type=item.get("itemtype") or "",
                grade=clean_html(item.get("gradeformatted")),
                range=clean_html(item.get("rangeformatted")) or rng,
                percentage=clean_html(item.get("percentageformatted")),
                feedback=clean_html(item.get("feedback"), 500),
                graded=wib(item.get("gradedategraded")),
            ))
    return out


def deadlines(s: SceleSession, days: int = 14, limit: int = 25) -> list[Deadline]:
    """Return upcoming deadlines across all courses within N days."""
    now = int(time.time())
    data = s.ws("core_calendar_get_action_events_by_timesort",
                timesortfrom=now - 3600, timesortto=now + int(days) * 86400,
                limitnum=min(max(int(limit), 1), 50)) or {}
    out = []
    for e in data.get("events") or []:
        c = e.get("course") or {}
        out.append(Deadline(
            name=clean_html(e.get("name")),
            course=c.get("shortname") or c.get("fullname") or "",
            course_id=str(c.get("id") or ""),
            when=wib(e.get("timesort")),
            due_in=until(e.get("timesort")),
            type=e.get("normalisedeventtypetext") or (e.get("action") or {}).get("name") or "",
            url=e.get("url") or "",
        ))
    return out


def _month_range(start: int, end: int) -> list[tuple[int, int]]:
    """(year, month) pairs covering the window [start, end] (epoch seconds)."""
    lo = time.gmtime(start)
    hi = time.gmtime(end)
    y, m = lo.tm_year, lo.tm_mon
    months = []
    while (y, m) <= (hi.tm_year, hi.tm_mon):
        months.append((y, m))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return months


def calendar(s: SceleSession, days_back: int = 7, days_ahead: int = 30) -> list[CalendarEvent]:
    """Return calendar events from N days back to M days ahead (all event types)."""
    now = int(time.time())
    start, end = now - int(days_back) * 86400, now + int(days_ahead) * 86400
    seen: set[str] = set()
    out: list[CalendarEvent] = []
    for year, month in _month_range(start, end):
        view = s.ws("core_calendar_get_calendar_monthly_view", year=year, month=month,
                    courseid=1, categoryid=0, includenavigation=0, mini=1) or {}
        for week in view.get("weeks") or []:
            for day in week.get("days") or []:
                for e in day.get("events") or []:
                    ts = e.get("timesort") or e.get("timestart") or 0
                    eid = str(e.get("id"))
                    if eid in seen or not (start <= ts <= end):
                        continue
                    seen.add(eid)
                    out.append(CalendarEvent(
                        id=eid,
                        name=clean_html(e.get("name")),
                        when=wib(ts),
                        type=e.get("normalisedeventtypetext") or e.get("eventtype") or "",
                        course_id=str((e.get("course") or {}).get("id")
                                      or e.get("courseid") or ""),
                        description=clean_html(e.get("description"), 400),
                    ))
    out.sort(key=lambda e: e.when)
    return out


def notifications(s: SceleSession, limit: int = 20) -> list[Notification]:
    """Return the user's recent SCELE notifications (popup/notification feed)."""
    data = s.ws("message_popup_get_popup_notifications", useridto=s.userid(),
                newestfirst=1, limit=min(max(int(limit), 1), 50), offset=0) or {}
    out = []
    for n in data.get("notifications") or []:
        out.append(Notification(
            id=str(n.get("id")),
            subject=clean_html(n.get("subject")),
            sender=n.get("component") or "",
            time=wib(n.get("timecreated")),
            text=clean_html(n.get("fullmessagehtml") or n.get("smallmessage")
                            or n.get("text"), 400),
            read=bool(n.get("read")),
        ))
    return out


def people(s: SceleSession, course_id: str) -> list[Person]:
    """Return the people enrolled in a course."""
    data = s.ws("core_enrol_get_enrolled_users", courseid=int(course_id)) or []
    return [
        Person(
            id=str(u.get("id")),
            name=clean_html(u.get("fullname")),
            roles=[r.get("shortname") for r in (u.get("roles") or []) if r.get("shortname")],
            email=u.get("email") or "",
            groups=[g.get("name") for g in (u.get("groups") or []) if g.get("name")],
        )
        for u in data
    ]


def course_updates(s: SceleSession, course_id: str, since_days: int = 7) -> dict:
    """Return activities created/updated in a course in the last N days."""
    since = int(time.time() - int(since_days) * 86400)
    data = s.ws("core_course_get_updates_since", courseid=int(course_id), since=since) or {}
    items = []
    for inst in data.get("instances") or []:
        changed = sorted({u.get("name") for u in inst.get("updates") or [] if u.get("name")})
        items.append({"cmid": inst.get("id"), "module": inst.get("contextlevel"),
                      "changed": changed})
    return {"course_id": str(course_id), "since_days": int(since_days), "updated": items}


# ---------------------------------------------------------------- writes

def enrol(s: SceleSession, course_id: str, instance_id: str | None = None, key: str = "") -> bool:
    """Self-enrol into a course; returns True on success."""
    params = {"courseid": int(course_id)}
    if key:
        params["password"] = key
    if instance_id:
        params["instanceid"] = int(instance_id)
    resp = s.ws("enrol_self_enrol_user", **params) or {}
    return bool(resp.get("status"))


def forum_subscribe(s: SceleSession, forum_id: str, discussion_id: str | None = None,
                    state: bool = True) -> bool:
    """Subscribe to (or unsubscribe from) a forum. Forum-level only."""
    fid = _forum_instance_id(s, int(forum_id))
    resp = s.ws("mod_forum_set_subscription_state", forumid=fid,
                targetstate=1 if state else 0) or {}
    return bool(resp.get("subscribed", state)) if isinstance(resp, dict) else True


def forum_post(s: SceleSession, forum_id: str, subject: str, message: str) -> str:
    """Start a new discussion in a forum; returns the new discussion URL."""
    fid = _forum_instance_id(s, int(forum_id))
    resp = s.ws("mod_forum_add_discussion", forumid=fid, subject=subject,
                message=message) or {}
    did = resp.get("discussionid")
    return _discussion_url(s, did) if did else ""


def forum_reply(s: SceleSession, post_id: str, message: str, subject: str = "") -> str:
    """Reply to a forum post; returns the discussion URL when known."""
    params = {"postid": int(post_id), "message": message}
    if subject:
        params["subject"] = subject
    resp = s.ws("mod_forum_add_discussion_post", **params) or {}
    post = resp.get("post") if isinstance(resp.get("post"), dict) else {}
    did = post.get("discussionid")
    return _discussion_url(s, did) if did else ""


def submit_text(s: SceleSession, ref: str, text: str, final: bool = True) -> dict:
    """Save online text to an assignment; optionally submit for grading."""
    info = assignment_detail(s, ref)
    assignid = int(info.id)
    save = s.ws("mod_assign_save_submission", assignmentid=assignid,
                plugindata={"onlinetext_editor": {"text": text, "format": 1, "itemid": 0}})
    warnings = (save or [])
    result = {"ok": not warnings, "stage": "saved", "assignment_id": info.id,
              "chars": len(text), "warnings": warnings}
    if final and not warnings:
        result.update(_submit_for_grading(s, assignid))
    return result


def submit_file(s: SceleSession, ref: str, file_path: str, final: bool = True) -> dict:
    """Upload a local file to an assignment; optionally submit for grading."""
    path = os.path.abspath(file_path)
    if not os.path.isfile(path):
        raise RequestFailedError(f"not a file: {file_path}")
    info = assignment_detail(s, ref)
    assignid = int(info.id)
    draft = s.ws("core_files_get_unused_draft_itemid") or {}
    itemid = draft.get("itemid") if isinstance(draft, dict) else draft
    with open(path, "rb") as fh:
        up = s.http.post(
            f"{s.base}/webservice/upload.php",
            data={"token": s.token, "filearea": "draft", "itemid": str(itemid)},
            files={"file_1": (os.path.basename(path), fh)},
            timeout=120,
        )
    up.raise_for_status()
    uploaded = up.json()
    if isinstance(uploaded, dict) and uploaded.get("error"):
        raise RequestFailedError(f"upload rejected: {uploaded['error']}")
    save = s.ws("mod_assign_save_submission", assignmentid=assignid,
                plugindata={"files_filemanager": int(itemid)})
    warnings = (save or [])
    result = {"ok": not warnings, "stage": "file saved", "assignment_id": info.id,
              "file": os.path.basename(path), "warnings": warnings}
    if final and not warnings:
        result.update(_submit_for_grading(s, assignid))
    return result


def _submit_for_grading(s: SceleSession, assignid: int) -> dict:
    resp = s.ws("mod_assign_submit_for_grading", assignmentid=assignid,
                acceptsubmissionstatement=1)
    warnings = resp or []
    return {"stage": "submitted for grading" if not warnings else "draft kept",
            "final_submit": "ok" if not warnings else warnings}


# ---------------------------------------------------------------- downloads

def download(
    s: SceleSession,
    url_or_cmid: str,
    out_dir: Path,
    progress: Callable[[int, int | None], None] | None = None,
) -> Path:
    """Download a pluginfile URL (or a resource cmid) to out_dir."""
    target = str(url_or_cmid)
    if target.isdigit():
        url = _cmid_fileurl(s, target)
    else:
        url = s.pluginfile_url(target)
    resp = s.http.get(url, params={"forcedownload": "1"}, stream=True, timeout=120)
    resp.raise_for_status()
    disp = resp.headers.get("content-disposition", "")
    fname = ""
    if "filename=" in disp:
        fname = disp.split("filename=", 1)[1].strip('"; ')
    fname = fname or url.split("?", 1)[0].rstrip("/").rsplit("/", 1)[-1] or "download"
    fname = os.path.basename(fname.replace("\\", "/")) or "download"
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = (out_dir / fname).resolve()
    if dest.parent != out_dir.resolve():
        raise RequestFailedError(f"refusing path-traversing filename: {fname!r}")
    total_header = resp.headers.get("content-length")
    try:
        total = int(total_header) if total_header else None
    except (TypeError, ValueError):
        total = None
    downloaded = 0
    if progress:
        progress(downloaded, total)
    try:
        with open(dest, "wb") as fh:
            for chunk in resp.iter_content(8192):
                if not chunk:
                    continue
                fh.write(chunk)
                downloaded += len(chunk)
                if progress:
                    progress(downloaded, total)
    finally:
        resp.close()
    return dest


def _cmid_fileurl(s: SceleSession, cmid: str) -> str:
    cm = _course_module(s, cmid)
    contents = s.ws("core_course_get_contents", courseid=int(cm["course"]),
                    options=[{"name": "cmid", "value": int(cmid)}]) or []
    for sec in contents:
        for m in sec.get("modules") or []:
            if str(m.get("id")) == str(cmid):
                for f in m.get("contents") or []:
                    if f.get("fileurl"):
                        return s.pluginfile_url(f["fileurl"])
    raise RequestFailedError(f"no downloadable file on module {cmid}")
