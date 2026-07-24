from tests.conftest import login
from tests.test_me import make_practice, FUTURE, PAST
from tests.test_close import confirm_all_parts


def closed_practice_with_my_status(client, status_body):
    pid = make_practice(client, FUTURE)
    login(client, "김소", "m1")
    client.put(f"/practices/{pid}/me", json=status_body)
    confirm_all_parts(client, pid)
    assert client.post(f"/practices/{pid}/close").status_code == 200
    return pid


def test_stats_counts_closed_only(client):
    closed_practice_with_my_status(client, {"status": "present"})
    closed_practice_with_my_status(
        client, {"status": "late", "reason": "버스", "eta": "19:30"})
    make_practice(client, PAST)  # open 상태 — 집계 제외
    login(client, "김소", "m1")
    body = client.get("/me/stats").json()
    assert body == {"total": 2, "present": 1, "late": 1, "absent": 0,
                    "rate": 1.0}


def test_stats_auto_absent_counted(client):
    pid = make_practice(client, PAST)   # 아무도 입력 안 함
    confirm_all_parts(client, pid)
    client.post(f"/practices/{pid}/close")
    login(client, "김소", "m1")
    body = client.get("/me/stats").json()
    assert body == {"total": 1, "present": 0, "late": 0, "absent": 1,
                    "rate": 0.0}


def test_stats_empty(client):
    login(client, "김소", "m1")
    assert client.get("/me/stats").json()["total"] == 0
