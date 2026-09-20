"""행정 일정 권한: 단장·홍보가 등록·수정·취소·삭제한다. 지휘 일정은 지휘자만.

취소·삭제는 그 일정의 출석 기록까지 지운다. 막지는 않고, 화면이 스냅숏의
attendance_count 로 몇 건이 사라지는지 경고한 뒤 요청한다.
"""
import pytest
from fastapi import HTTPException

from app.operations import Operations
from tests.test_operations_part import StubStore


def member(member_id, admin_role="", role="member", part="bass"):
    return {"id": member_id, "name": member_id, "student_id": member_id, "part": part,
            "role": role, "admin_role": admin_role, "active": True}


HEAD, PUBLICITY, TREASURER, PLAIN = member("h", "head"), member("p", "publicity"), member("t", "treasurer"), member("m")
CONDUCTOR = member("c", role="conductor", part="conductor")
SEMESTER = {"id": "sem", "state": "active", "year": 2026, "half": 2}
NEW_ID = "12345678-1234-1234-1234-123456789012"


def make(category="행정"):
    ops = Operations(StubStore())
    event = {"id": "e", "title": "총회", "category": category, "kind": "행정" if category == "행정" else "연습",
             "status": "open", "starts_at": "2026-10-01T19:00:00", "ends_at": "2026-10-01T21:00:00",
             "semester": "sem", "confirmations": {}, "songs": [], "edited_at": "t", "takes_attendance": False}
    record = {"id": "a1", "event": "e", "member": "m", "status": "출석"}
    data = {"members": [HEAD, PUBLICITY, TREASURER, PLAIN, CONDUCTOR], "events": [event],
            "attendance": [record], "semesters": [SEMESTER], "songs": []}
    return ops, data


def body(kind="admin", **extra):
    return {"kind": kind, "title": "총회", "starts_at": "2026-10-01T19:00:00",
            "ends_at": "2026-10-01T21:00:00", "semester": "sem", **extra}


def writes(ops):
    return [kind for kind, _, _ in ops.store.saved]


@pytest.mark.parametrize("who", [HEAD, PUBLICITY])
def test_head_and_publicity_register_admin_events(who):
    ops, data = make()
    ops.save_event(data, who, body(request_id=NEW_ID))
    assert writes(ops) == ["events"]


@pytest.mark.parametrize("who", [HEAD, PUBLICITY])
def test_head_and_publicity_edit_admin_events(who):
    ops, data = make()
    ops.save_event(data, who, body(), "e")
    assert writes(ops) == ["events"]


@pytest.mark.parametrize("who", [TREASURER, PLAIN, CONDUCTOR])
def test_others_cannot_register_admin_events(who):
    ops, data = make()
    with pytest.raises(HTTPException) as exc:
        ops.save_event(data, who, body(request_id=NEW_ID))
    assert exc.value.status_code == 403
    assert writes(ops) == []


@pytest.mark.parametrize("who", [HEAD, PUBLICITY])
@pytest.mark.parametrize("delete", [False, True])
def test_head_and_publicity_cancel_or_delete_admin_events(who, delete):
    ops, data = make()
    ops.store.delete = lambda page_id: ops.store.saved.append(("delete", page_id, None))
    assert ops.remove_event(data, who, "e", delete=delete) == {"ok": True}
    assert ("delete", "a1", None) in ops.store.saved   # 일정에 적힌 출석도 같이 지워진다


@pytest.mark.parametrize("who", [TREASURER, PLAIN, CONDUCTOR])
@pytest.mark.parametrize("delete", [False, True])
def test_others_cannot_cancel_or_delete_admin_events(who, delete):
    """지우면 출석 기록까지 사라진다. 권한이 없으면 아무것도 쓰지 않고 거절해야 한다."""
    ops, data = make()
    with pytest.raises(HTTPException) as exc:
        ops.remove_event(data, who, "e", delete=delete)
    assert exc.value.status_code == 403
    assert ops.store.saved == []


def test_publicity_gains_nothing_on_conductor_events():
    ops, data = make("지휘")
    for call in (lambda: ops.save_event(data, PUBLICITY, body("rehearsal"), "e"),
                 lambda: ops.save_event(data, PUBLICITY, body("rehearsal", request_id=NEW_ID)),
                 lambda: ops.remove_event(data, PUBLICITY, "e")):
        with pytest.raises(HTTPException) as exc:
            call()
        assert exc.value.status_code == 403
    assert ops.store.saved == []
