import pytest

from app import auth
from tests.conftest import login


def test_token_roundtrip():
    t = auth.sign_token(7, "s")
    assert auth.verify_token(t, "s") == 7
    assert auth.verify_token(t, "other") is None
    assert auth.verify_token("garbage", "s") is None


def test_health(client):
    assert client.get("/health").json() == {"ok": True}


def test_login_success_sets_cookie(client):
    body = login(client, "김소", "m1")
    assert body["role"] == "member" and body["part"] == "soprano"
    assert "session" in client.cookies


def test_login_wrong_name_401(client):
    r = client.post("/auth/login", json={"name": "김수", "student_id": "m1"})
    assert r.status_code == 401


def test_login_inactive_member_401(client, conn):
    conn.execute("UPDATE members SET active=0 WHERE student_id='m1'")
    conn.commit()
    r = client.post("/auth/login", json={"name": "김소", "student_id": "m1"})
    assert r.status_code == 401


@pytest.mark.xfail(reason="Task 4에서 /practices 라우트 추가")
def test_protected_route_without_cookie_401(client):
    assert client.get("/practices").status_code == 401
