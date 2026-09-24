"""건의함: 누구나 이름을 남겨 보내고, 집행부(단장·홍보·총무)만 전부 읽고 처리 상태를 바꾼다."""
import copy

import pytest
from fastapi import HTTPException

from app.operations import Operations
from tests.test_admin_attendance import HEAD, SOPRANO, SnapshotStore
from tests.test_operations_part import StubStore

REQUEST = "12345678-1234-1234-1234-123456789012"


def member(member_id, admin_role="", role="member", part="tenor"):
    return {"id": member_id, "name": f"이름{member_id}", "student_id": member_id, "part": part,
            "role": role, "admin_role": admin_role, "active": True}


PUBLICITY, TREASURER, PLAIN = member("p", "publicity"), member("t", "treasurer"), member("m")
LEADER, CONDUCTOR = member("l", role="part_leader"), member("c", role="conductor", part="conductor")


def suggestion(sid="x", author="m", status="접수", **extra):
    return {"id": sid, "key": "", "title": "요약", "body": "연습실이 추워요", "member": author,
            "member_name": f"이름{author}", "part": "테너", "created_at": "2026-09-24T10:00:00",
            "status": status, "handled_by": "", "handled_at": "", "edited_at": "t", **extra}


def make(*rows):
    ops = Operations(StubStore())
    return ops, {"suggestions": list(rows)}


def saved(ops):
    return [values for kind, values, _ in ops.store.saved if kind == "suggestions"]


def test_anyone_sends_with_name_and_part():
    ops, data = make()
    ops.save_suggestion(data, PLAIN, {"body": "  연습 전날까지 악보를 올려 주세요\n자세한 이유는…  ", "request_id": REQUEST})
    [values] = saved(ops)
    assert values["member"] == "m" and values["member_name"] == "이름m" and values["part"] == "테너"
    assert values["status"] == "접수" and values["key"] == REQUEST
    assert values["title"] == "연습 전날까지 악보를 올려 주세요"      # 노션 목록에서 보이는 첫 줄
    assert values["body"].endswith("자세한 이유는…")


def test_long_first_line_is_shortened_for_the_title_only():
    ops, data = make()
    ops.save_suggestion(data, PLAIN, {"body": "가" * 100, "request_id": REQUEST})
    [values] = saved(ops)
    assert values["title"] == "가" * 60 + "…" and values["body"] == "가" * 100


@pytest.mark.parametrize("body", ["", "   ", "가" * 2001])
def test_empty_or_too_long_is_rejected(body):
    ops, data = make()
    with pytest.raises(HTTPException) as exc:
        ops.save_suggestion(data, PLAIN, {"body": body, "request_id": REQUEST})
    assert exc.value.status_code == 422 and saved(ops) == []


@pytest.mark.parametrize("who", [HEAD, PUBLICITY, TREASURER])
def test_every_executive_marks_status_and_is_recorded(who):
    ops, data = make(suggestion())
    ops.mark_suggestion(data, who, "x", {"status": "확인함"})
    [values] = saved(ops)
    assert values["status"] == "확인함" and values["handled_by"] == who["name"] and values["handled_at"]


@pytest.mark.parametrize("who", [PLAIN, LEADER, CONDUCTOR])
def test_others_cannot_mark(who):
    ops, data = make(suggestion(author=who["id"]))   # 자기가 낸 건의라도
    with pytest.raises(HTTPException) as exc:
        ops.mark_suggestion(data, who, "x", {"status": "반영함"})
    assert exc.value.status_code == 403 and saved(ops) == []


def test_unknown_status_is_rejected():
    ops, data = make(suggestion())
    with pytest.raises(HTTPException) as exc:
        ops.mark_suggestion(data, HEAD, "x", {"status": "완료"})
    assert exc.value.status_code == 422 and saved(ops) == []


def test_back_to_received_clears_who_handled_it():
    ops, data = make(suggestion(status="반영함", handled_by="단장", handled_at="2026-09-24T11:00:00"))
    ops.mark_suggestion(data, PUBLICITY, "x", {"status": "접수"})
    [values] = saved(ops)
    assert values == {"status": "접수", "handled_by": "", "handled_at": ""}


def test_same_status_writes_nothing():
    ops, data = make(suggestion(status="확인함"))
    assert ops.mark_suggestion(data, HEAD, "x", {"status": "확인함"}) == {"ok": True}
    assert saved(ops) == []


# ---------- 화면에 내려가는 스냅숏 ----------


class SuggestionStore(SnapshotStore):
    def __init__(self, rows):
        super().__init__([], [])
        self.rows = rows

    def read(self, kind, fresh=False):
        return copy.deepcopy(self.rows) if kind == "suggestions" else super().read(kind, fresh)


def test_snapshot_executive_sees_all_member_sees_own():
    rows = [suggestion("a", author="s", created_at="2026-09-20T09:00:00"),
            suggestion("b", author="c", status="반영함", created_at="2026-09-22T09:00:00"),
            suggestion("c", author="s", status="", created_at="2026-09-23T09:00:00"),
            suggestion("blank", author="s", body="")]                      # 노션에서 만든 빈 행
    ops = Operations(SuggestionStore(rows))
    head = ops.snapshot("h")
    assert [x["id"] for x in head["suggestions"]] == ["c", "b", "a"]    # 최신순, 빈 행 제외
    assert head["open_suggestions"] == 2                                  # 접수 + 상태 빈 칸
    mine = Operations(SuggestionStore(rows)).snapshot("s")
    assert [x["id"] for x in mine["suggestions"]] == ["c", "a"]
    assert mine["open_suggestions"] == 0
    assert SOPRANO["admin_role"] == "" and HEAD["admin_role"] == "head"
