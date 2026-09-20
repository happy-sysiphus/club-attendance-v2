"""행정 일정의 출석은 선택이다. 지휘 일정과 기존 기록은 그대로 출석 대상으로 남는다.

노션의 'Open house'는 유형만 '행정'이고 분류는 '지휘'라 출석 44건이 쌓여 있다.
이 변경 뒤에도 분류가 지휘인 일정은 '출석 받기' 칸과 무관하게 출석 대상이어야 한다.
"""
import copy
from threading import RLock

import pytest
from fastapi import HTTPException

from app.operations import Operations, has_attendance
from tests.test_operations_part import StubStore

HEAD = {"id": "h", "name": "단장", "student_id": "h1", "part": "bass",
        "role": "member", "admin_role": "head", "active": True}
CONDUCTOR = {"id": "c", "name": "지휘", "student_id": "c1", "part": "conductor",
             "role": "conductor", "admin_role": "", "active": True}
SOPRANO = {"id": "s", "name": "김소프", "student_id": "s1", "part": "soprano",
           "role": "member", "admin_role": "", "active": True}
SEMESTER = {"id": "sem", "state": "active", "year": 2026, "half": 2}


def event(**overrides):
    base = {"id": "e", "title": "총회", "category": "행정", "kind": "행정", "status": "open",
            "starts_at": "2026-10-01T19:00:00", "ends_at": "2026-10-01T21:00:00", "semester": "sem",
            "confirmations": {}, "songs": [], "edited_at": "t", "takes_attendance": False}
    return {**base, **overrides}


def make(ev, attendance=()):
    ops = Operations(StubStore())
    data = {"members": [HEAD, CONDUCTOR, SOPRANO], "events": [ev], "attendance": list(attendance),
            "semesters": [SEMESTER], "songs": []}
    return ops, data


def edit_body(**extra):
    return {"kind": "admin", "title": "총회", "starts_at": "2026-10-01T19:00:00",
            "ends_at": "2026-10-01T21:00:00", "semester": "sem", **extra}


def saved_event(ops):
    return [values for kind, values, _ in ops.store.saved if kind == "events"][-1]


def test_admin_event_without_attendance_is_not_an_attendance_target():
    ops, data = make(event())
    with pytest.raises(HTTPException) as exc:
        ops.attendance_for(data, SOPRANO, "e", {"status": "present"})
    assert exc.value.status_code == 409


def test_admin_event_with_attendance_accepts_marking():
    ops, data = make(event(takes_attendance=True))
    assert ops.attendance_for(data, SOPRANO, "e", {"status": "present"})["status"] == "present"


def test_open_house_style_event_keeps_attendance():
    """유형만 '행정', 분류는 '지휘'인 기존 일정. '출석 받기' 칸이 비어 있어도 출석 대상이다."""
    legacy = event(category="지휘", kind="행정", takes_attendance=False)
    assert has_attendance(legacy)
    ops, data = make(legacy)
    assert ops.attendance_for(data, SOPRANO, "e", {"status": "present"})["status"] == "present"


def test_head_turns_attendance_on():
    ops, data = make(event())
    ops.save_event(data, HEAD, edit_body(takes_attendance=True), "e")
    assert saved_event(ops)["takes_attendance"] is True


def test_edit_without_the_flag_keeps_current_setting():
    """예전 화면처럼 값을 안 보내는 수정이 출석을 몰래 끄지 않는다."""
    ops, data = make(event(takes_attendance=True))
    ops.save_event(data, HEAD, edit_body(), "e")
    assert saved_event(ops)["takes_attendance"] is True


def test_cannot_turn_off_when_records_exist():
    record = {"id": "a1", "event": "e", "member": "s", "status": "출석"}
    ops, data = make(event(takes_attendance=True), [record])
    with pytest.raises(HTTPException) as exc:
        ops.save_event(data, HEAD, edit_body(takes_attendance=False), "e")
    assert exc.value.status_code == 409
    assert [k for k, _, _ in ops.store.saved] == []


def test_can_turn_off_before_anyone_marked_and_sign_offs_reset():
    """끌 때 파트 확인도 비운다. 안 그러면 다시 켰을 때 예전 확인 때문에 단원이 잠긴다."""
    ops, data = make(event(takes_attendance=True, confirmations={"soprano": {"at": "t", "by": "파트장"}}))
    ops.save_event(data, HEAD, edit_body(takes_attendance=False), "e")
    assert saved_event(ops)["takes_attendance"] is False
    assert saved_event(ops)["confirmations"] == "{}"


def test_new_admin_event_defaults_to_no_attendance():
    ops, data = make(event())
    body = {**edit_body(), "request_id": "12345678-1234-1234-1234-123456789012"}
    ops.save_event(data, HEAD, body)
    assert saved_event(ops)["takes_attendance"] is False


@pytest.mark.parametrize("value", ["false", "true", 1, None])
def test_flag_must_be_a_real_boolean(value):
    """문자열 'false' 가 켜짐으로 읽히지 않게, 불리언이 아니면 거절한다."""
    ops, data = make(event(takes_attendance=True))
    with pytest.raises(HTTPException) as exc:
        ops.save_event(data, HEAD, edit_body(takes_attendance=value), "e")
    assert exc.value.status_code == 422


def test_conductor_event_ignores_the_flag():
    """지휘 일정은 항상 출석 대상이라 '출석 받기' 칸을 쓰지 않는다."""
    practice = event(category="지휘", kind="연습", title="정기연습")
    ops, data = make(practice)
    body = {**edit_body(kind="rehearsal", title="정기연습", takes_attendance=False)}
    ops.save_event(data, CONDUCTOR, body, "e")
    assert "takes_attendance" not in saved_event(ops)
    assert has_attendance(practice)


# ---------- 화면 단위: 노션의 Open house 가 배포 뒤에도 그대로 보이는가 ----------


class SnapshotStore:
    """snapshot() 이 읽는 만큼만 흉내 낸다. 읽는 동안 쓰기가 일어나면 saved 에 남는다."""
    lock = RLock()
    roster_warnings, ledger_categories = [], []

    def __init__(self, events, attendance):
        self.events, self.attendance, self.saved = events, attendance, []

    def bootstrap(self):
        pass

    def read(self, kind, fresh=False):
        semester = {"id": "sem", "title": "2026년 2학기", "year": 2026, "half": 2, "state": "active",
                    "carry": 0, "carry_at": "", "previous": "", "transition_at": ""}
        return copy.deepcopy({"semesters": [semester], "songs": [], "events": self.events, "materials": [],
                              "acknowledgements": [], "attendance": self.attendance, "ledger": []}[kind])

    def roster(self, fresh=False):
        return copy.deepcopy([HEAD, CONDUCTOR, SOPRANO])

    def ensure_semester_views(self, semester):
        pass

    def save(self, *args):
        self.saved.append(args)

    def delete(self, *args):
        self.saved.append(("delete",) + args)


def test_closed_open_house_survives_in_stats_attendance_and_board():
    """배포 직후 상태: '출석 받기' 칸이 막 생겨 비어 있다(None). 기록이 출석률·내 출석·현황판에 그대로 남는다."""
    open_house = {"id": "oh", "title": "Open house", "category": "지휘", "kind": "행정", "status": "closed",
                  "starts_at": "2026-09-14T18:30:00", "ends_at": "2026-09-14T21:00:00", "semester": "sem",
                  "confirmations": "{}", "songs": [], "song_order": "", "photo_meta": "{}", "photos": [],
                  "edited_at": "t", "takes_attendance": None, "all_day": False, "place": "", "description": "",
                  "key": "", "created_by": "", "closed_at": "2026-09-14T22:00:00"}
    row = {"id": "a1", "event": "oh", "member": "s", "status": "출석", "source": "member",
           "reason": "", "eta": "", "updated_at": "2026-09-14T18:25:00"}
    store = SnapshotStore([open_house], [row])
    ops = Operations(store)
    member = ops.snapshot("s")
    assert member["stats"]["present"] == 1 and member["stats"]["total"] == 1
    assert "oh" in member["my_attendance"]
    assert "oh" in ops.snapshot("c")["boards"]
    # 취소·삭제 경고에 쓰는 건수. 일정에 연결된 출석 행 전부를 센다(지울 때 전부 지워지므로).
    assert member["events"][0]["attendance_count"] == 1
    assert store.saved == []
