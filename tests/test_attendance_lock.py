"""단원 본인 출석 입력의 잠금 기준: 연습 시작 시각이 아니라 자기 파트의 확인 완료.

예전에는 연습이 시작되면 단원이 늦게 와도 본인 출석을 못 눌렀다.
이제는 파트장(반주자는 지휘자)이 그 파트를 확인 완료하기 전까지 열려 있다.
"""
import pytest
from fastapi import HTTPException

from app.operations import Operations
from tests.test_operations_part import StubStore

STARTED = "2026-01-01T19:00:00"   # 이미 시작한 연습
UPCOMING = "2099-01-01T19:00:00"  # 아직 시작 전

SOPRANO = {"id": "s", "name": "김소프", "student_id": "s1", "part": "soprano",
           "role": "member", "admin_role": "", "active": True}
SOPRANO_LEADER = {"id": "ls", "name": "파트장소프", "student_id": "ls1", "part": "soprano",
                  "role": "part_leader", "admin_role": "", "active": True}
BASS = {"id": "b", "name": "김베이스", "student_id": "b1", "part": "bass",
        "role": "member", "admin_role": "", "active": True}
ACCOMPANIST = {"id": "a", "name": "반주", "student_id": "a1", "part": "accompanist",
               "role": "member", "admin_role": "", "active": True}
SIGNED = {"at": "2026-01-01T19:30:00", "by": "파트장"}


def make(starts_at=STARTED, confirmations=None, status="open"):
    ops = Operations(StubStore())
    event = {"id": "e", "title": "정기연습", "category": "지휘", "kind": "연습", "status": status,
             "starts_at": starts_at, "semester": "sem", "confirmations": dict(confirmations or {})}
    data = {"members": [SOPRANO, SOPRANO_LEADER, BASS, ACCOMPANIST], "events": [event], "attendance": []}
    return ops, data


def attendance_writes(ops):
    return [values for kind, values, _ in ops.store.saved if kind == "attendance"]


def test_member_can_mark_after_practice_started():
    """늦게 온 단원도 파트 확인 전이면 본인 출석을 누를 수 있다. 예전엔 여기서 403 이었다."""
    ops, data = make(STARTED)
    result = ops.attendance_for(data, SOPRANO, "e", {"status": "present"})
    assert result["status"] == "present"
    assert [w["source"] for w in attendance_writes(ops)] == ["member"]


@pytest.mark.parametrize("starts_at", [STARTED, UPCOMING])
def test_member_locked_once_own_part_confirmed(starts_at):
    """확인 완료가 잠금 기준이라 시작 전이어도 확인됐으면 막힌다."""
    ops, data = make(starts_at, {"soprano": SIGNED})
    with pytest.raises(HTTPException) as exc:
        ops.attendance_for(data, SOPRANO, "e", {"status": "absent"})
    assert exc.value.status_code == 403
    assert attendance_writes(ops) == []


def test_other_parts_confirmation_does_not_lock_member():
    ops, data = make(STARTED, {"bass": SIGNED})
    assert ops.attendance_for(data, SOPRANO, "e", {"status": "present"})["status"] == "present"


def test_part_leader_still_corrects_confirmed_part_and_clears_sign_off():
    """파트장 수정은 확인 후에도 되고, 기존처럼 그 파트 확인이 풀린다. 다른 파트 확인은 남는다."""
    ops, data = make(STARTED, {"soprano": SIGNED, "bass": SIGNED})
    result = ops.attendance_for(data, SOPRANO_LEADER, "e", {"status": "late", "reason": "버스", "eta": "19:20"}, target_id="s")
    assert result["status"] == "late"
    events = [values for kind, values, _ in ops.store.saved if kind == "events"]
    assert '"soprano"' not in events[-1]["confirmations"]
    assert '"bass"' in events[-1]["confirmations"]


def test_closed_practice_still_rejects_member():
    ops, data = make(STARTED, {}, status="closed")
    with pytest.raises(HTTPException) as exc:
        ops.attendance_for(data, SOPRANO, "e", {"status": "present"})
    assert exc.value.status_code == 409


def test_member_cannot_bypass_lock_through_staff_endpoint():
    """확인 뒤 단원이 파트장용 경로(/members/본인)로 돌아가도 막힌다."""
    ops, data = make(STARTED, {"soprano": SIGNED})
    with pytest.raises(HTTPException) as exc:
        ops.attendance_for(data, SOPRANO, "e", {"status": "present"}, target_id="s")
    assert exc.value.status_code == 403
    assert attendance_writes(ops) == []


def test_accompanist_locked_after_conductor_confirms():
    """반주자 파트는 지휘자가 확인한다. 확인되면 반주자 본인도 잠긴다."""
    ops, data = make(STARTED, {"accompanist": SIGNED})
    with pytest.raises(HTTPException) as exc:
        ops.attendance_for(data, ACCOMPANIST, "e", {"status": "present"})
    assert exc.value.status_code == 403


# ---------- 확인 완료: 확인하는 사람이 못 본 입력을 잠그지 않는다 ----------


def row(member, updated_at):
    return {"id": f"row-{member}", "event": "e", "member": member, "status": "출석",
            "source": "member", "updated_at": updated_at}


def confirmation_writes(ops):
    return [values for kind, values, _ in ops.store.saved if kind == "events"]


def test_confirm_rejected_when_part_changed_after_board_loaded():
    """19:05 에 연 현황판으로 19:08 에 확인하는데, 19:07 에 단원이 직접 입력했다."""
    ops, data = make(STARTED)
    data["attendance"] = [row("s", "2026-01-01T19:07:00")]
    with pytest.raises(HTTPException) as exc:
        ops.confirm_part(data, SOPRANO_LEADER, "e", "soprano", seen_at="2026-01-01T19:05:00")
    assert exc.value.status_code == 409
    assert confirmation_writes(ops) == []


def test_confirm_allowed_when_board_is_current():
    """본 시각과 같은 입력은 이미 본 것이고, 다른 파트의 새 입력은 상관없다."""
    ops, data = make(STARTED)
    data["attendance"] = [row("s", "2026-01-01T19:05:00"), row("b", "2026-01-01T19:09:00")]
    assert ops.confirm_part(data, SOPRANO_LEADER, "e", "soprano", seen_at="2026-01-01T19:05:00") == {"confirmed": True}
    assert '"soprano"' in confirmation_writes(ops)[-1]["confirmations"]


@pytest.mark.parametrize("seen_at", [None, "", "어제"])
def test_confirm_requires_readable_board_time(seen_at):
    """시각이 없거나 깨졌으면 확인하지 않는다. 배포 전 열어 둔 탭이 검사를 건너뛰지 않게."""
    ops, data = make(STARTED)
    with pytest.raises(HTTPException) as exc:
        ops.confirm_part(data, SOPRANO_LEADER, "e", "soprano", seen_at=seen_at)
    assert exc.value.status_code == 409
