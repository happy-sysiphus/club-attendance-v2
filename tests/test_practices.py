from tests.conftest import login

BODY = {"title": "정기연습", "starts_at": "2026-09-01T19:00:00", "place": "음악관"}


def test_conductor_creates_practice(client):
    login(client, "지휘자", "c1")
    r = client.post("/practices", json=BODY)
    assert r.status_code == 201
    assert r.json()["status"] == "open"


def test_member_cannot_create(client):
    login(client, "김소", "m1")
    assert client.post("/practices", json=BODY).status_code == 403


def test_bad_starts_at_422(client):
    login(client, "지휘자", "c1")
    r = client.post("/practices", json={"title": "x", "starts_at": "내일저녁"})
    assert r.status_code == 422


def test_list_visible_to_member(client):
    login(client, "지휘자", "c1")
    client.post("/practices", json=BODY)
    login(client, "김소", "m1")
    r = client.get("/practices")
    assert r.status_code == 200 and len(r.json()) == 1


def test_blank_title_rejected_on_create(client):
    login(client, "지휘자", "c1")
    assert client.post("/practices", json={**BODY, "title": "   "}).status_code == 422


def test_blank_title_rejected_on_update(client):
    login(client, "지휘자", "c1")
    pid = client.post("/practices", json=BODY).json()["id"]
    assert client.put(f"/practices/{pid}", json={**BODY, "title": "  "}).status_code == 422


def test_offset_starts_at_normalized_and_board_works(client):
    login(client, "지휘자", "c1")
    r = client.post("/practices", json={"title": "p",
                                        "starts_at": "2099-09-01T19:00:00+09:00"})
    assert r.status_code == 201
    starts_at = r.json()["starts_at"]
    assert "+" not in starts_at and "Z" not in starts_at
    assert starts_at == "2099-09-01T19:00:00"
    pid = r.json()["id"]
    board = client.get(f"/practices/{pid}/board")
    assert board.status_code == 200
    assert board.json()["practice"]["starts_at"] == "2099-09-01T19:00:00"


def test_update_and_delete_open_only(client, conn):
    login(client, "지휘자", "c1")
    pid = client.post("/practices", json=BODY).json()["id"]
    r = client.put(f"/practices/{pid}", json={**BODY, "place": "대강당"})
    assert r.status_code == 200 and r.json()["place"] == "대강당"
    conn.execute("UPDATE practices SET status='closed' WHERE id=?", (pid,))
    conn.commit()
    assert client.put(f"/practices/{pid}", json=BODY).status_code == 409
    assert client.delete(f"/practices/{pid}").status_code == 409
    conn.execute("UPDATE practices SET status='open' WHERE id=?", (pid,))
    conn.commit()
    assert client.delete(f"/practices/{pid}").status_code == 200
    assert client.get("/practices").json() == []
