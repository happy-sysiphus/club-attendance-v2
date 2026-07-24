import pytest
from fastapi.testclient import TestClient

from app import db
from app.main import create_app

SEED = [
    ("지휘자", "c1", "soprano", "conductor"),
    ("파트장소프라노", "ps", "soprano", "part_leader"),
    ("파트장알토", "pa", "alto", "part_leader"),
    ("파트장테너", "pt", "tenor", "part_leader"),
    ("파트장베이스", "pb", "bass", "part_leader"),
    ("김소", "m1", "soprano", "member"),
    ("김알", "m2", "alto", "member"),
]


@pytest.fixture()
def app(tmp_path):
    application = create_app(str(tmp_path / "test.db"))
    conn = application.state.conn
    conn.executemany(
        "INSERT INTO members (name, student_id, part, role) VALUES (?,?,?,?)",
        SEED)
    conn.commit()
    return application


@pytest.fixture()
def conn(app):
    return app.state.conn


@pytest.fixture()
def client(app):
    return TestClient(app)


def login(client, name, student_id):
    r = client.post("/auth/login", json={"name": name, "student_id": student_id})
    assert r.status_code == 200, r.text
    return r.json()
