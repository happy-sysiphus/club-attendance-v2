from tests.conftest import login
from tests.test_me import make_practice, FUTURE, PAST


def member_id_of(conn, student_id):
    return conn.execute("SELECT id FROM members WHERE student_id=?",
                        (student_id,)).fetchone()["id"]


def test_part_leader_edits_own_part_after_start(client, conn):
    pid = make_practice(client, PAST)
    mid = member_id_of(conn, "m1")
    login(client, "파트장소프라노", "ps")
    r = client.put(f"/practices/{pid}/members/{mid}",
                   json={"status": "late", "reason": "늦잠", "eta": "19:40"})
    assert r.status_code == 200
    assert r.json()["status"] == "late" and r.json()["source"] == "part_leader"


def test_part_leader_cannot_edit_other_part(client, conn):
    pid = make_practice(client, FUTURE)
    mid = member_id_of(conn, "m2")  # alto
    login(client, "파트장소프라노", "ps")
    r = client.put(f"/practices/{pid}/members/{mid}", json={"status": "present"})
    assert r.status_code == 403


def test_conductor_edits_anyone(client, conn):
    pid = make_practice(client, FUTURE)
    mid = member_id_of(conn, "m2")
    login(client, "지휘자", "c1")
    r = client.put(f"/practices/{pid}/members/{mid}", json={"status": "present"})
    assert r.status_code == 200 and r.json()["source"] == "conductor"


def test_member_cannot_use_admin_endpoint(client, conn):
    pid = make_practice(client, FUTURE)
    mid = member_id_of(conn, "m1")
    login(client, "김소", "m1")
    r = client.put(f"/practices/{pid}/members/{mid}", json={"status": "present"})
    assert r.status_code == 403


def test_edit_locked_when_closed(client, conn):
    pid = make_practice(client, FUTURE)
    mid = member_id_of(conn, "m1")
    conn.execute("UPDATE practices SET status='closed' WHERE id=?", (pid,))
    conn.commit()
    login(client, "지휘자", "c1")
    r = client.put(f"/practices/{pid}/members/{mid}", json={"status": "present"})
    assert r.status_code == 409


def test_confirm_own_part_idempotent(client):
    pid = make_practice(client, FUTURE)
    login(client, "파트장테너", "pt")
    assert client.post(f"/practices/{pid}/part/confirm",
                       json={"part": "tenor"}).status_code == 200
    assert client.post(f"/practices/{pid}/part/confirm",
                       json={"part": "tenor"}).status_code == 200


def test_confirm_other_part_403_but_conductor_ok(client):
    pid = make_practice(client, FUTURE)
    login(client, "파트장테너", "pt")
    assert client.post(f"/practices/{pid}/part/confirm",
                       json={"part": "bass"}).status_code == 403
    login(client, "지휘자", "c1")
    assert client.post(f"/practices/{pid}/part/confirm",
                       json={"part": "bass"}).status_code == 200


def test_confirm_bad_part_422(client):
    pid = make_practice(client, FUTURE)
    login(client, "지휘자", "c1")
    assert client.post(f"/practices/{pid}/part/confirm",
                       json={"part": "baritone"}).status_code == 422
