"""파트 미정 단원(part="")이 로그인·출석 로직을 깨뜨리지 않는지 확인한다.

이 변경 전에는 명단에서 파트 없는 행을 통째로 버려 로그인이 막혔고, 활성 상태로 두면
close_attendance 의 PART_KO[""] 가 KeyError 를 던져 지휘자가 마감을 못 했다.
"""
import types

import pytest
from fastapi import HTTPException

from app.operations import Operations
from app.operations_store import OperationsStore

# ---------- 출석 로직용 스텁 ----------


class StubStore:
    """노션 대신 호출만 기록한다."""

    def __init__(self):
        self.saved, self.parts = [], []

    def save(self, kind, values, page_id=None):
        self.saved.append((kind, values, page_id))
        return page_id or "new-page"

    def set_part(self, member_id, korean_part):
        self.parts.append((member_id, korean_part))


CONDUCTOR = {"id": "c", "name": "지휘", "student_id": "c1", "part": "conductor",
             "role": "conductor", "admin_role": "", "active": True}
BASS = {"id": "b", "name": "김베이스", "student_id": "b1", "part": "bass",
        "role": "member", "admin_role": "", "active": True}
UNSET = {"id": "u", "name": "임유빈", "student_id": "u1", "part": "",
         "role": "member", "admin_role": "", "active": True}

EVENT = {"id": "e", "title": "정기연습", "category": "지휘", "kind": "연습",
         "status": "open", "starts_at": "2026-09-10T19:00:00", "semester": "s",
         "confirmations": {"soprano": {}, "alto": {}, "tenor": {}, "bass": {}}}


def make(*members):
    ops = Operations(StubStore())
    data = {"members": list(members), "events": [dict(EVENT)], "attendance": [],
            "semesters": [], "songs": [], "materials": [], "acknowledgements": [],
            "ledger": []}
    return ops, data


def test_close_succeeds_with_unassigned_member():
    """파트 미정 단원이 있어도 마감이 된다. 이 줄이 예전엔 KeyError 로 500 이었다."""
    ops, data = make(CONDUCTOR, BASS, UNSET)
    assert ops.close_attendance(data, CONDUCTOR, "e") == {"status": "closed"}


def test_unassigned_member_gets_no_absence_row():
    """현황판 어느 파트에도 없는 사람에게 자동 결석을 남기지 않는다."""
    ops, data = make(CONDUCTOR, BASS, UNSET)
    ops.close_attendance(data, CONDUCTOR, "e")
    written = [v["member"] for kind, v, _ in ops.store.saved if kind == "attendance"]
    assert written == ["b"]


def test_unassigned_member_cannot_save_attendance():
    ops, data = make(CONDUCTOR, BASS, UNSET)
    with pytest.raises(HTTPException) as exc:
        ops.attendance_for(data, UNSET, "e", {"status": "present"})
    assert exc.value.status_code == 403


def test_choose_part_writes_korean_name():
    ops, data = make(UNSET)
    assert ops.choose_part(data, UNSET, {"part": "tenor"}) == {"part": "tenor"}
    assert ops.store.parts == [("u", "테너")]


def test_choose_part_rejects_second_change():
    """한 번 정해지면 본인은 못 바꾼다 — 변경은 지휘자가 노션에서."""
    ops, data = make(BASS)
    with pytest.raises(HTTPException) as exc:
        ops.choose_part(data, BASS, {"part": "tenor"})
    assert exc.value.status_code == 403
    assert ops.store.parts == []


@pytest.mark.parametrize("part", ["accompanist", "conductor", "soprano2", ""])
def test_choose_part_rejects_non_vocal(part):
    """반주자·지휘자는 본인이 고를 수 없다 — 지휘 탭 권한이 딸려오기 때문."""
    ops, data = make(UNSET)
    with pytest.raises(HTTPException) as exc:
        ops.choose_part(data, UNSET, {"part": part})
    assert exc.value.status_code == 422
    assert ops.store.parts == []


# ---------- 명단 읽기 ----------


def page(name, student_id, part, role="단원", active=True):
    def rich(value):
        return {"type": "rich_text", "rich_text": [{"plain_text": value}] if value else []}
    return {"id": student_id, "properties": {
        "이름": {"type": "title", "title": [{"plain_text": name}] if name else []},
        "학번": rich(student_id),
        "파트": {"type": "select", "select": {"name": part} if part else None},
        "역할": {"type": "select", "select": {"name": role}},
        "활성": {"type": "checkbox", "checkbox": active},
    }}


def roster(*pages):
    """_roster() 만 돌리기 위한 최소 노션 대역."""
    query = lambda **kwargs: {"results": list(pages), "has_more": False}
    client = types.SimpleNamespace(databases=types.SimpleNamespace(query=query))
    store = OperationsStore(types.SimpleNamespace(client=client), None)
    store.ids["roster"] = "db"
    return store, store._roster()


def test_roster_keeps_member_without_part():
    store, rows = roster(page("임유빈", "u1", None))
    assert [(m["name"], m["part"]) for m in rows] == [("임유빈", "")]
    assert store.roster_warnings == []


def test_roster_still_drops_part_typo():
    """빈 파트는 '미정'이지만 오타는 여전히 제외하고 경고로 알린다."""
    store, rows = roster(page("김베이스", "b1", "베이스"), page("오타", "x1", "쏘프라노"))
    assert [m["name"] for m in rows] == ["김베이스"]
    assert len(store.roster_warnings) == 1
    assert "쏘프라노" in store.roster_warnings[0]


def test_roster_still_drops_missing_student_id():
    store, rows = roster(page("김베이스", "b1", "베이스"), page("학번없음", "", None))
    assert [m["name"] for m in rows] == ["김베이스"]
    assert len(store.roster_warnings) == 1
