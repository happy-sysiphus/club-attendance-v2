def test_index_served_at_root(client):
    r = client.get("/")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert 'id="view"' in r.text


def test_static_assets_served(client):
    assert client.get("/app.js").status_code == 200
    assert client.get("/style.css").status_code == 200


def test_api_not_shadowed_by_static_mount(client):
    # 노션 미설정이면 운영 API는 503으로 거부한다(설계). 정적 마운트에 가려졌다면 404/405가 나온다.
    r = client.post("/auth/login", json={"name": "없음", "student_id": "x"})
    assert r.status_code == 503
    assert client.get("/api/state").status_code in (401, 503)
