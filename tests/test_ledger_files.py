"""회계 항목 증빙 파일: 총무만 올리고 지운다. 노션은 부르지 않고 저장 호출만 기록한다."""
from types import SimpleNamespace
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

from app import auth, config
from app.main import create_app

KEY = "12345678-1234-1234-1234-123456789012"
EXISTING = {"name": "old--영수증.pdf", "type": "file", "file": {"url": "https://files.example/old"}}


@pytest.fixture()
def finance(tmp_path):
    app = create_app(str(tmp_path / "t.db"), notion=SimpleNamespace(client=None))
    ops, saved = app.state.operations, []
    members = {"t": {"id": "t", "name": "총무", "admin_role": "treasurer", "role": "member"},
               "m": {"id": "m", "name": "단원", "admin_role": "", "role": "member"}}
    data = {"ledger": [{"id": "row", "title": "간식", "files": [EXISTING]}]}
    ops.context = lambda member_id: (data, members[member_id])
    ops.store.upload = lambda file, name, mime, size: {"name": name, "type": "file_upload", "file_upload": {"id": "up"}}
    ops.store.save = lambda kind, values, page_id=None: saved.append((kind, values, page_id)) or page_id

    def client(member_id):
        c = TestClient(app)
        c.cookies.set("session", auth.sign_token(member_id, config.SECRET_KEY))
        return c
    return SimpleNamespace(client=client, saved=saved, ops=ops, data=data)


def upload(client, filename="receipt.jpg"):
    return client.post("/api/upload/ledger/row", content=b"bytes", headers={"X-Filename": quote(filename), "X-Request-Id": KEY})   # 화면도 encodeURIComponent 로 보낸다


def test_treasurer_attaches_a_file_and_keeps_existing_ones(finance):
    assert upload(finance.client("t")).status_code == 200
    kind, values, page_id = finance.saved[-1]
    assert (kind, page_id) == ("ledger", "row")
    assert [f["name"] for f in values["files"]] == ["old--영수증.pdf", f"{KEY}--receipt.jpg"]
    assert values["files"][0] == {"name": "old--영수증.pdf", "type": "file", "file": {"url": "https://files.example/old"}}


def test_members_cannot_attach_or_delete(finance):
    assert upload(finance.client("m")).status_code == 403
    assert finance.client("m").delete("/api/ledger/row/files/old--영수증.pdf").status_code == 403
    assert finance.saved == []


def test_any_extension_is_accepted_and_notion_picks_the_type(finance, monkeypatch):
    seen = []
    ops = finance.ops
    monkeypatch.setattr(ops.store, "upload", lambda file, name, mime, size: seen.append((name, mime)) or {"name": name, "type": "file_upload", "file_upload": {"id": "up"}})
    assert upload(finance.client("t"), "정산.xlsx").status_code == 200
    assert seen == [(f"{KEY}--정산.xlsx", None)]   # content_type 을 안 보내면 노션이 확장자로 정한다


def test_types_notion_rejects_are_zipped(finance, monkeypatch):
    """.hwp 처럼 노션이 거절하는 확장자는 원본을 zip 에 담아 '이름.hwp.zip' 으로 저장한다."""
    import io, zipfile
    from app.operations_store import UnsupportedFileType
    calls = []

    def fake_upload(file, name, mime, size):
        if not name.endswith(".zip"):
            raise UnsupportedFileType(name)
        calls.append((name, mime, zipfile.ZipFile(io.BytesIO(file.read())).read("결산보고.hwp")))
        return {"name": name, "type": "file_upload", "file_upload": {"id": "up"}}
    monkeypatch.setattr(finance.ops.store, "upload", fake_upload)
    assert upload(finance.client("t"), "결산보고.hwp").status_code == 200
    assert calls == [(f"{KEY}--결산보고.hwp.zip", "application/zip", b"bytes")]
    assert finance.saved[-1][1]["files"][-1]["name"] == f"{KEY}--결산보고.hwp.zip"


def test_retry_of_a_zipped_upload_is_not_saved_twice(finance):
    finance.data["ledger"][0]["files"].append({"name": f"{KEY}--결산보고.hwp.zip", "type": "file", "file": {"url": "https://files.example/z"}})
    assert upload(finance.client("t"), "결산보고.hwp").status_code == 200
    assert finance.saved == []


def test_treasurer_deletes_one_file(finance):
    assert finance.client("t").delete("/api/ledger/row/files/old--영수증.pdf").status_code == 200
    assert finance.saved[-1] == ("ledger", {"files": []}, "row")
