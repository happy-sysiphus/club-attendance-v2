import pytest

from tests.conftest import login
from tests.test_me import make_practice, FUTURE, PAST


def test_member_gets_403(client):
    pid = make_practice(client, FUTURE)
    login(client, "김소", "m1")
    assert client.get(f"/practices/{pid}/board").status_code == 403


def test_part_leader_sees_only_own_part(client):
    pid = make_practice(client, FUTURE)
    login(client, "파트장알토", "pa")
    body = client.get(f"/practices/{pid}/board").json()
    assert list(body["parts"].keys()) == ["alto"]
    names = [m["name"] for m in body["parts"]["alto"]["members"]]
    assert "김알" in names and "김소" not in names


def test_conductor_sees_all_parts_and_totals(client):
    pid = make_practice(client, FUTURE)
    login(client, "김소", "m1")
    client.put(f"/practices/{pid}/me",
               json={"status": "late", "reason": "버스", "eta": "19:30"})
    login(client, "지휘자", "c1")
    body = client.get(f"/practices/{pid}/board").json()
    assert set(body["parts"]) == {"soprano", "alto", "tenor", "bass"}
    assert body["totals"]["late"] == 1
    # 시드 7명: late 1 + 미확정 6 (시작 전이라 unconfirmed)
    assert body["totals"]["unconfirmed"] == 6


def test_auto_absent_counted_after_start(client):
    pid = make_practice(client, PAST)
    login(client, "지휘자", "c1")
    body = client.get(f"/practices/{pid}/board").json()
    assert body["totals"]["absent"] == 7
    assert body["totals"]["unconfirmed"] == 0
    soprano = body["parts"]["soprano"]["members"]
    assert all(m["status"] == "absent" and m["source"] == "auto"
               for m in soprano)


def test_inactive_member_excluded(client, conn):
    conn.execute("UPDATE members SET active=0 WHERE student_id='m2'")
    conn.commit()
    pid = make_practice(client, FUTURE)
    login(client, "지휘자", "c1")
    body = client.get(f"/practices/{pid}/board").json()
    names = [m["name"] for m in body["parts"]["alto"]["members"]]
    assert "김알" not in names


@pytest.mark.xfail(reason="Task 7에서 confirm 라우트 추가")
def test_confirmed_flag_flips_after_confirm(client):
    pid = make_practice(client, FUTURE)
    login(client, "파트장테너", "pt")
    client.post(f"/practices/{pid}/part/confirm", json={"part": "tenor"})
    body = client.get(f"/practices/{pid}/board").json()
    assert body["parts"]["tenor"]["confirmed"] is True


def test_roster_warnings_conductor_only(client, app):
    app.state.roster_warnings[:] = ["명단 3행 파트 오타"]
    pid = make_practice(client, FUTURE)
    login(client, "지휘자", "c1")
    assert client.get(f"/practices/{pid}/board").json()[
        "roster_warnings"] == ["명단 3행 파트 오타"]
    login(client, "파트장알토", "pa")
    assert client.get(f"/practices/{pid}/board").json()["roster_warnings"] == []
