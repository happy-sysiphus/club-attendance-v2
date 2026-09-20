import pytest


@pytest.mark.parametrize("path", ["/apple-touch-icon.png", "/apple-touch-icon-precomposed.png", "/favicon.ico"])
def test_default_icon_names_serve_app_icon(client, path):
    """페이지를 안 읽고 기본 이름으로 찾아오는 아이콘 요청이 404 대신 앱 아이콘을 받는다."""
    r = client.get(path)
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    assert r.content == client.get("/assets/glee-icon.png").content


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


def test_manifest_icons_exist(client):
    """안드로이드 홈 화면 추가용 매니페스트. 적어 둔 아이콘이 실제로 내려와야 한다."""
    r = client.get("/manifest.json")
    assert r.status_code == 200
    manifest = r.json()
    assert manifest["display"] == "standalone" and manifest["short_name"] == "글리"
    assert {i["sizes"] for i in manifest["icons"]} >= {"192x192", "512x512"}
    for icon in manifest["icons"]:
        assert client.get(icon["src"]).headers["content-type"] == "image/png"
    assert '<link rel="manifest" href="/manifest.json">' in client.get("/").text


def test_mscz_is_stored_as_zip_and_downloaded_under_its_own_name():
    """노션은 .mscz 업로드를 거절한다. .zip 을 덧붙여 저장하고, 열 때만 원래 이름으로 되돌린다."""
    from app.operations_routes import download_name, notion_name
    assert notion_name("아리랑 Soprano.MSCZ") == "아리랑 Soprano.MSCZ.zip"
    assert notion_name("악보.pdf") == "악보.pdf"
    assert download_name("아리랑 Soprano.MSCZ.zip") == "아리랑 Soprano.MSCZ"
    assert download_name("악보.pdf") is None and download_name("자료.zip") is None
