from app import db
from tests.conftest import login
from tests.test_me import make_practice, FUTURE, PAST


def confirm_all_parts(client, pid):
    login(client, "지휘자", "c1")
    for part in db.PARTS:
        assert client.post(f"/practices/{pid}/part/confirm",
                           json={"part": part}).status_code == 200


def test_close_blocked_until_all_parts_confirmed(client):
    pid = make_practice(client, PAST)
    login(client, "지휘자", "c1")
    r = client.post(f"/practices/{pid}/close")
    assert r.status_code == 409
    assert set(r.json()["detail"]["missing_parts"]) == set(db.PARTS)


def test_close_materializes_auto_absent(client, conn):
    pid = make_practice(client, PAST)
    confirm_all_parts(client, pid)
    assert client.post(f"/practices/{pid}/close").status_code == 200
    rows = conn.execute(
        "SELECT status, source FROM attendance WHERE practice_id=?",
        (pid,)).fetchall()
    assert len(rows) == 7  # 시드 전원 행 생성
    assert all(r["status"] == "absent" and r["source"] == "auto" for r in rows)
    p = conn.execute("SELECT * FROM practices WHERE id=?", (pid,)).fetchone()
    assert p["status"] == "closed" and p["closed_at"] is not None


def test_close_excludes_inactive_members(client, conn):
    conn.execute("UPDATE members SET active=0 WHERE student_id='m2'")
    conn.commit()
    pid = make_practice(client, PAST)
    confirm_all_parts(client, pid)
    client.post(f"/practices/{pid}/close")
    assert conn.execute(
        "SELECT COUNT(*) FROM attendance WHERE practice_id=?",
        (pid,)).fetchone()[0] == 6  # 활성 6명만 확정


def test_close_keeps_entered_statuses(client, conn):
    pid = make_practice(client, FUTURE)
    login(client, "김소", "m1")
    client.put(f"/practices/{pid}/me",
               json={"status": "late", "reason": "버스", "eta": "19:30"})
    confirm_all_parts(client, pid)
    client.post(f"/practices/{pid}/close")
    row = conn.execute(
        "SELECT a.status, a.source FROM attendance a JOIN members m "
        "ON m.id=a.member_id WHERE a.practice_id=? AND m.student_id='m1'",
        (pid,)).fetchone()
    assert row["status"] == "late" and row["source"] == "member"


def test_close_idempotent(client):
    pid = make_practice(client, PAST)
    confirm_all_parts(client, pid)
    assert client.post(f"/practices/{pid}/close").status_code == 200
    assert client.post(f"/practices/{pid}/close").status_code == 200


def test_reopen_keeps_confirmations_then_reclose(client, conn):
    pid = make_practice(client, PAST)
    confirm_all_parts(client, pid)
    client.post(f"/practices/{pid}/close")
    assert client.post(f"/practices/{pid}/reopen").json()["status"] == "open"
    n = conn.execute("SELECT COUNT(*) FROM part_confirmations "
                     "WHERE practice_id=?", (pid,)).fetchone()[0]
    assert n == 4
    # 재오픈 후 즉시 재마감 가능 (확인 유지 덕분)
    assert client.post(f"/practices/{pid}/close").status_code == 200


def test_reopen_requires_conductor(client):
    pid = make_practice(client, PAST)
    confirm_all_parts(client, pid)
    client.post(f"/practices/{pid}/close")
    login(client, "파트장소프라노", "ps")
    assert client.post(f"/practices/{pid}/reopen").status_code == 403
