from fastapi.testclient import TestClient

from app import db
from app.main import create_app
from app.notion import NotionStore
from tests.conftest import SEED, login
from tests.fake_notion import FakeNotionClient, checkbox, rich, select, title
from tests.test_close import confirm_all_parts
from tests.test_me import PAST

KO_PART = {"soprano": "소프라노", "alto": "알토",
           "tenor": "테너", "bass": "베이스"}
KO_ROLE = {"member": "단원", "part_leader": "파트장", "conductor": "지휘자"}


def add_roster_member(fake, roster_db, name, sid, part, role):
    fake.pages.create(parent={"database_id": roster_db},
                      properties={"이름": title(name), "학번": rich(sid),
                                  "파트": select(KO_PART[part]),
                                  "역할": select(KO_ROLE[role]),
                                  "활성": checkbox(True)})


def boot_with_notion(tmp_path, preload_roster):
    """빈 SQLite + FakeNotion으로 create_app — 부팅 복원 경로.

    prep.db는 일부러 앱 DB(app.db)와 다른 파일이다: '노션에는 DB가 이미
    있는데 SQLite는 통째로 날아간' 재배포 시나리오를 재현한다. 앱은
    ensure_databases의 재발견(부모 페이지 자식 탐색)으로 같은 노션 DB를
    찾아야 한다.
    """
    fake = FakeNotionClient()
    store = NotionStore(fake, "parent")
    prep = db.connect(str(tmp_path / "prep.db"))
    store.ensure_databases(prep)
    roster_db = prep.execute(
        "SELECT value FROM settings WHERE key='roster_db_id'").fetchone()[0]
    for name, sid, part, role in preload_roster:
        add_roster_member(fake, roster_db, name, sid, part, role)
    app = create_app(str(tmp_path / "app.db"), notion=store)
    return app, fake, roster_db


def att_db_id(app):
    return app.state.conn.execute(
        "SELECT value FROM settings WHERE key='attendance_db_id'"
    ).fetchone()[0]


def test_boot_restores_roster(tmp_path):
    app, fake, _ = boot_with_notion(tmp_path, SEED)
    with TestClient(app) as client:   # with 블록이 lifespan 실행
        body = login(client, "김소", "m1")
        assert body["part"] == "soprano"
    assert len(fake.dbs) == 2  # 재발견 성공 — 노션 DB 중복 생성 없음


def test_close_syncs_to_notion_in_background(tmp_path):
    app, fake, _ = boot_with_notion(tmp_path, SEED)
    with TestClient(app) as client:
        login(client, "지휘자", "c1")
        pid = client.post("/practices", json=PAST).json()["id"]
        confirm_all_parts(client, pid)
        assert client.post(f"/practices/{pid}/close").status_code == 200
        # TestClient는 응답 후 백그라운드 태스크를 즉시 실행
        assert len(fake.dbs[att_db_id(app)]["pages"]) == 7
        assert app.state.conn.execute(
            "SELECT notion_synced_at FROM practices WHERE id=?",
            (pid,)).fetchone()[0] is not None


def test_reopen_edit_reclose_updates_same_notion_pages(tmp_path):
    """스펙 §12-4: 재오픈 후 수정 → 재마감 시 노션 update(create 아님)."""
    app, fake, _ = boot_with_notion(tmp_path, SEED)
    with TestClient(app) as client:
        login(client, "지휘자", "c1")
        pid = client.post("/practices", json=PAST).json()["id"]
        confirm_all_parts(client, pid)
        client.post(f"/practices/{pid}/close")
        pages_before = len(fake.dbs[att_db_id(app)]["pages"])

        client.post(f"/practices/{pid}/reopen")
        mid = app.state.conn.execute(
            "SELECT id FROM members WHERE student_id='m1'").fetchone()["id"]
        client.put(f"/practices/{pid}/members/{mid}",
                   json={"status": "late", "reason": "버스", "eta": "19:30"})
        client.post(f"/practices/{pid}/close")

        att_db = att_db_id(app)
        assert len(fake.dbs[att_db]["pages"]) == pages_before  # 중복 없음
        page_id = app.state.conn.execute(
            "SELECT a.notion_page_id FROM attendance a JOIN members m "
            "ON m.id=a.member_id WHERE a.practice_id=? AND m.student_id='m1'",
            (pid,)).fetchone()[0]
        status_prop = fake.dbs[att_db]["pages"][page_id]["properties"]["상태"]
        assert status_prop["select"]["name"] == "지각"


def test_new_member_in_notion_can_login_via_refresh(tmp_path):
    """스펙 §4.2: 캐시 미스 시 명단 재조회 후 로그인 성공."""
    app, fake, roster_db = boot_with_notion(tmp_path, SEED)
    with TestClient(app) as client:
        add_roster_member(fake, roster_db, "신입", "n1", "bass", "member")
        body = login(client, "신입", "n1")   # 캐시에 없음 → refresh 후 매칭
        assert body["part"] == "bass"


def test_boot_survives_notion_failure(tmp_path):
    """노션이 부팅 시 죽어도 앱은 떠야 한다 — /health가 cron-job.org 생명줄."""
    class BoomNotion:
        def ensure_databases(self, conn):
            raise RuntimeError("notion down")

        def refresh_roster(self, conn, state):
            raise RuntimeError("notion down")

        def restore_archive(self, conn, state):
            raise RuntimeError("notion down")

    app = create_app(str(tmp_path / "app.db"), notion=BoomNotion())
    with TestClient(app) as client:   # lifespan이 여기서 실행 — 예외 없어야 함
        assert client.get("/health").json() == {"ok": True}
