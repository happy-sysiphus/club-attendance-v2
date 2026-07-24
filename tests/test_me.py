from tests.conftest import login

FUTURE = {"title": "p", "starts_at": "2099-01-01T19:00:00"}
PAST = {"title": "p", "starts_at": "2000-01-01T19:00:00"}


def make_practice(client, body):
    login(client, "지휘자", "c1")
    return client.post("/practices", json=body).json()["id"]


def test_me_default_unconfirmed(client):
    pid = make_practice(client, FUTURE)
    login(client, "김소", "m1")
    assert client.get(f"/practices/{pid}/me").json() == {
        "status": None, "source": None, "reason": None, "eta": None}


def test_me_put_late_and_read_back(client):
    pid = make_practice(client, FUTURE)
    login(client, "김소", "m1")
    r = client.put(f"/practices/{pid}/me",
                   json={"status": "late", "reason": "버스", "eta": "19:30"})
    assert r.status_code == 200
    body = client.get(f"/practices/{pid}/me").json()
    assert body["status"] == "late" and body["source"] == "member"


def test_me_put_late_without_reason_422(client):
    pid = make_practice(client, FUTURE)
    login(client, "김소", "m1")
    r = client.put(f"/practices/{pid}/me", json={"status": "late", "eta": "19:30"})
    assert r.status_code == 422


def test_me_locked_after_start(client):
    pid = make_practice(client, PAST)
    login(client, "김소", "m1")
    r = client.put(f"/practices/{pid}/me", json={"status": "present"})
    assert r.status_code == 403


def test_me_shows_auto_absent_after_start(client, conn):
    pid = make_practice(client, PAST)
    login(client, "김소", "m1")
    body = client.get(f"/practices/{pid}/me").json()
    assert body["status"] == "absent" and body["source"] == "auto"
    # 지연 평가 핵심 계약: 표시만 absent, DB에는 아직 아무 행도 확정 안 됨
    assert conn.execute("SELECT COUNT(*) FROM attendance WHERE practice_id=?",
                        (pid,)).fetchone()[0] == 0


def test_me_locked_when_closed(client, conn):
    pid = make_practice(client, FUTURE)
    conn.execute("UPDATE practices SET status='closed' WHERE id=?", (pid,))
    conn.commit()
    login(client, "김소", "m1")
    r = client.put(f"/practices/{pid}/me", json={"status": "present"})
    assert r.status_code == 409
