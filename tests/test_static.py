from tests.conftest import login


def test_index_served_at_root(client):
    r = client.get("/")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert '<main id="view">' in r.text


def test_static_assets_served(client):
    assert client.get("/app.js").status_code == 200
    assert client.get("/style.css").status_code == 200


def test_api_not_shadowed_by_static_mount(client):
    login(client, "김소", "m1")
    assert client.get("/practices").status_code == 200
    assert client.post("/auth/login",
                       json={"name": "없음", "student_id": "x"}).status_code == 401
