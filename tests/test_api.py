"""api.py maps Moodle web-service payloads onto the CLI's dataclasses.

A FakeSession returns canned JSON per wsfunction — no network, no token.
"""


import time

from scele import api
from scele.models import (
    AssignmentStatus, CalendarEvent, Deadline, Discussion, Grade, Notification, Person,
    Post,
)
from scele.session import RequestFailedError


class FakeSession:
    base = "https://scele.example"
    token = "T"

    def __init__(self, responses: dict):
        self.responses = responses
        self.calls = []

    def ws(self, wsfunction, **params):
        self.calls.append((wsfunction, params))
        if wsfunction not in self.responses:
            raise AssertionError(f"unexpected ws call: {wsfunction}")
        val = self.responses[wsfunction]
        return val(params) if callable(val) else val

    def userid(self):
        return 8830

    def pluginfile_url(self, url):
        return url + "?token=T"


def test_my_courses_sorts_and_maps():
    s = FakeSession({
        "core_enrol_get_users_courses": [
            {"id": 2, "shortname": "DDP2", "fullname": "Dasar Pemrograman 2", "progress": 40.2},
            {"id": 1, "shortname": "ALG", "fullname": "Algoritma", "hidden": True},
            {"id": 3, "shortname": "ANP", "fullname": "Analisis Numerik", "progress": None},
        ],
    })
    out = api.my_courses(s)
    assert [c.shortname for c in out] == ["ANP", "DDP2"]  # hidden dropped, sorted
    assert out[1].progress == 40.2
    assert out[1].url == "https://scele.example/course/view.php?id=2"


def test_thread_builds_parent_and_depth():
    s = FakeSession({
        "mod_forum_get_discussion_posts": {"posts": [
            {"id": 1, "parentid": 0, "subject": "D05", "message": "<p>root</p>",
             "timecreated": 0, "author": {"fullname": "Aimee"}},
            {"id": 2, "parentid": 1, "subject": "Re: D05", "message": "hi",
             "timecreated": 0, "author": {"fullname": "Naya"}},
            {"id": 3, "parentid": 2, "subject": "Re: D05", "message": "yo",
             "timecreated": 0, "author": {"fullname": "Marco"}},
        ]},
    })
    posts = api.thread(s, "62561")
    assert [p.depth for p in posts] == [0, 1, 2]
    assert posts[2].parent == "2"
    assert posts[0].body == "root"
    assert all(isinstance(p, Post) for p in posts)


def test_thread_depth_with_branches_and_shared_ancestors():
    s = FakeSession({
        "mod_forum_get_discussion_posts": {"posts": [
            {"id": 1, "parentid": 0, "message": "r", "timecreated": 0},
            {"id": 2, "parentid": 1, "message": "a", "timecreated": 0},
            {"id": 3, "parentid": 1, "message": "b", "timecreated": 0},
            {"id": 4, "parentid": 3, "message": "c", "timecreated": 0},
            {"id": 5, "parentid": 4, "message": "d", "timecreated": 0},
        ]},
    })
    posts = api.thread(s, "1")
    assert {p.id: p.depth for p in posts} == {"1": 0, "2": 1, "3": 1, "4": 2, "5": 3}


def test_assignment_status_summarizes_submission():
    s = FakeSession({
        "core_course_get_course_module": {"cm": {"id": 55010, "instance": 900,
                                                 "course": 4234, "name": "HW1"}},
        "mod_assign_get_submission_status": {"lastattempt": {
            "gradingstatus": "graded",
            "submission": {"status": "submitted", "attemptnumber": 0,
                           "timemodified": 0, "plugins": [
                               {"type": "file", "fileareas": [{"files": [
                                   {"filename": "a.pdf", "fileurl": "https://x/a.pdf"}]}]},
                           ]},
        }},
    })
    st = api.assignment(s, "55010")
    assert isinstance(st, AssignmentStatus)
    assert st.name == "HW1"
    assert st.fields["Submission status"] == "SUBMITTED"
    assert st.fields["Grading status"] == "graded"
    assert st.files == [{"name": "a.pdf", "url": "https://x/a.pdf"}]


def test_grades_maps_items():
    s = FakeSession({
        "gradereport_user_get_grade_items": {"usergrades": [{"gradeitems": [
            {"itemname": "Midterm", "itemtype": "mod", "gradeformatted": "88.00",
             "grademin": 0, "grademax": 100, "percentageformatted": "88.00 %",
             "feedback": "<p>nice</p>", "gradedategraded": 0},
        ]}]},
    })
    out = api.grades(s, "4234")
    assert out == [Grade(item="Midterm", type="mod", grade="88.00", range="0–100",
                         percentage="88.00 %", feedback="nice",
                         graded=out[0].graded)]


def test_deadlines_maps_action_events():
    s = FakeSession({
        "core_calendar_get_action_events_by_timesort": {"events": [
            {"name": "HW due", "timesort": 4102444800, "url": "https://x",
             "course": {"shortname": "DDP2", "id": 2},
             "normalisedeventtypetext": "Assignment"},
        ]},
    })
    out = api.deadlines(s)
    assert isinstance(out[0], Deadline) and out[0].course == "DDP2"


def test_calendar_flattens_monthly_view_and_filters_window():
    now = int(time.time())
    soon, later = now + 3 * 86400, now + 999 * 86400
    view = {"weeks": [{"days": [
        {"events": [
            {"id": 7, "name": "Lecture", "timesort": soon, "eventtype": "course",
             "normalisedeventtypetext": "Course event", "course": {"id": 2},
             "description": "<p>room A</p>"},
            {"id": 8, "name": "Way off", "timesort": later, "course": {"id": 2}},
        ]},
    ]}]}
    s = FakeSession({"core_calendar_get_calendar_monthly_view": view})
    out = api.calendar(s, days_back=0, days_ahead=30)
    assert [e.id for e in out] == ["7"]  # id 8 is outside the window
    assert isinstance(out[0], CalendarEvent) and out[0].description == "room A"


def test_notifications_maps_popup_feed():
    s = FakeSession({
        "message_popup_get_popup_notifications": {"notifications": [
            {"id": 5, "subject": "SECTION A &amp; B graded", "component": "mod_assign",
             "timecreated": 0, "fullmessagehtml": "<p>done</p>", "read": True},
        ]},
    })
    n = api.notifications(s)[0]
    assert isinstance(n, Notification) and n.read is True and n.text == "done"
    assert n.sender == "mod_assign" and n.subject == "SECTION A & B graded"


def test_course_detail_uses_contacts_for_teachers():
    s = FakeSession({
        "core_course_get_courses_by_field": {"courses": [
            {"id": 4234, "shortname": "Komas", "fullname": "Komputer &amp; Masyarakat",
             "categoryname": "REG", "startdate": 0, "enddate": 0, "summary": "",
             "contacts": [{"id": 437, "fullname": "R. Yugo K. Isal"}]},
        ]},
    })
    d = api.course_detail(s, "4234")
    assert d.fullname == "Komputer & Masyarakat"
    assert d.teachers == [{"id": "437", "name": "R. Yugo K. Isal"}]
    assert [c[0] for c in s.calls] == ["core_course_get_courses_by_field"]  # no roster fetch


def test_people_maps_roles():
    s = FakeSession({
        "core_enrol_get_enrolled_users": [
            {"id": 1, "fullname": "Dr Yugo", "roles": [{"shortname": "editingteacher"}],
             "email": "y@x", "groups": [{"name": "A"}]},
        ],
    })
    p = api.people(s, "4234")[0]
    assert isinstance(p, Person)
    assert p.roles == ["editingteacher"] and p.groups == ["A"]


def test_forum_accepts_a_cmid_and_resolves_it_to_the_instance():
    def discussions(params):
        if params["forumid"] != 17474:
            raise RequestFailedError("Unable to find forum with id")
        return {"discussions": [
            {"discussion": 62561, "name": "D05", "userfullname": "Aimee",
             "numreplies": 25, "created": 0, "timemodified": 0},
        ]}

    s = FakeSession({
        "mod_forum_get_forum_discussions": discussions,
        "mod_forum_get_forum_discussions_paginated": discussions,
        "core_course_get_course_module": {"cm": {"id": 222560, "instance": 17474,
                                                 "modname": "forum"}},
    })
    out = api.forum(s, "222560")  # 222560 is the activity cmid, 17474 the instance id
    assert len(out) == 1 and isinstance(out[0], Discussion)
    assert out[0].id == "62561"


def test_forum_uses_instance_id_directly_without_extra_calls():
    s = FakeSession({
        "mod_forum_get_forum_discussions": {"discussions": [
            {"discussion": 62561, "name": "D05", "userfullname": "Aimee", "numreplies": 1},
        ]},
    })
    assert api.forum(s, "17474")[0].id == "62561"
    assert [c[0] for c in s.calls] == ["mod_forum_get_forum_discussions"]


def test_forum_reply_passes_subject_when_given():
    s = FakeSession({"mod_forum_add_discussion_post": {"post": {"discussionid": 99}}})
    url = api.forum_reply(s, "553917", "thanks", subject="Custom")
    assert url == "https://scele.example/mod/forum/discuss.php?d=99"
    assert s.calls[0][1]["subject"] == "Custom"


def test_forum_reply_omits_subject_by_default():
    s = FakeSession({"mod_forum_add_discussion_post": {"post": {}}})
    api.forum_reply(s, "553917", "thanks")
    assert "subject" not in s.calls[0][1]
