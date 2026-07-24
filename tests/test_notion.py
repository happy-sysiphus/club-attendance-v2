import types

from app import db
from app.notion import NotionStore
from tests.fake_notion import (FakeNotionClient, checkbox, date, rich,
                               select, title)


def setting(conn, key):
    return conn.execute("SELECT value FROM settings WHERE key=?",
                        (key,)).fetchone()["value"]


def make_env(tmp_path):
    conn = db.connect(str(tmp_path / "n.db"))
    fake = FakeNotionClient()
    store = NotionStore(fake, "parent-page")
    store.ensure_databases(conn)
    state = types.SimpleNamespace(roster_warnings=[])
    return conn, fake, store, state


def add_roster_page(conn, fake, name, sid, part_ko, role_ko, active=True):
    db_id = setting(conn, "roster_db_id")
    page = fake.pages.create(
        parent={"database_id": db_id},
        properties={"이름": title(name), "학번": rich(sid),
                    "파트": select(part_ko), "역할": select(role_ko),
                    "활성": checkbox(active)})
    return page["id"]


def test_ensure_databases_idempotent(tmp_path):
    conn, fake, store, _ = make_env(tmp_path)
    ids = (setting(conn, "roster_db_id"), setting(conn, "attendance_db_id"))
    store.ensure_databases(conn)  # 두 번째 호출 — 새 DB 안 만듦
    assert (setting(conn, "roster_db_id"),
            setting(conn, "attendance_db_id")) == ids
    assert len(fake.dbs) == 2


def test_ensure_databases_rediscovers_after_sqlite_loss(tmp_path):
    """SQLite 유실 재현: settings가 빈 새 DB로 부팅해도 기존 노션 DB 재사용."""
    conn, fake, store, _ = make_env(tmp_path)
    ids = (setting(conn, "roster_db_id"), setting(conn, "attendance_db_id"))
    fresh = db.connect(str(tmp_path / "fresh.db"))  # settings 비어 있음
    store.ensure_databases(fresh)
    assert (setting(fresh, "roster_db_id"),
            setting(fresh, "attendance_db_id")) == ids
    assert len(fake.dbs) == 2  # 새 노션 DB를 만들지 않았음


def test_refresh_roster_upserts_and_deactivates(tmp_path):
    conn, fake, store, state = make_env(tmp_path)
    add_roster_page(conn, fake, "김소", "m1", "소프라노", "단원")
    store.refresh_roster(conn, state)
    row = conn.execute("SELECT * FROM members WHERE student_id='m1'").fetchone()
    assert row["part"] == "soprano" and row["role"] == "member"
    assert row["active"] == 1 and row["notion_page_id"]

    # 노션에서 사라진 멤버는 비활성화
    conn.execute("INSERT INTO members (name, student_id, part, role) "
                 "VALUES ('탈단자', 'gone1', 'alto', 'member')")
    conn.commit()
    store.refresh_roster(conn, state)
    assert conn.execute("SELECT active FROM members WHERE student_id='gone1'"
                        ).fetchone()["active"] == 0


def test_refresh_roster_bad_row_warns_and_skips(tmp_path):
    conn, fake, store, state = make_env(tmp_path)
    add_roster_page(conn, fake, "정상", "ok1", "알토", "단원")
    add_roster_page(conn, fake, "오타", "bad1", "바리톤", "단원")  # 없는 파트
    store.refresh_roster(conn, state)
    assert conn.execute("SELECT COUNT(*) FROM members").fetchone()[0] == 1
    assert len(state.roster_warnings) == 1
    assert "바리톤" in state.roster_warnings[0]


def test_refresh_roster_matches_by_property_id_after_rename(tmp_path):
    """지휘자가 노션에서 컬럼명을 바꿔도 속성 ID로 매칭돼야 한다."""
    import json as _json
    conn, fake, store, state = make_env(tmp_path)
    prop_ids = _json.loads(setting(conn, "roster_prop_ids"))
    db_id = setting(conn, "roster_db_id")
    # 컬럼명이 전부 바뀐 페이지 — 값 dict에 저장된 속성 ID를 부착
    fake.pages.create(
        parent={"database_id": db_id},
        properties={
            "성함": {**title("김소"), "id": prop_ids["이름"]},
            "학생번호": {**rich("m1"), "id": prop_ids["학번"]},
            "성부": {**select("소프라노"), "id": prop_ids["파트"]},
            "직책": {**select("단원"), "id": prop_ids["역할"]},
            "재적": {**checkbox(True), "id": prop_ids["활성"]},
        })
    store.refresh_roster(conn, state)
    row = conn.execute("SELECT * FROM members WHERE student_id='m1'").fetchone()
    assert row is not None and row["part"] == "soprano"
    assert state.roster_warnings == []


def test_sync_close_creates_then_updates(tmp_path):
    conn, fake, store, state = make_env(tmp_path)
    db_path = str(tmp_path / "n.db")
    conn.execute("INSERT INTO members (id, name, student_id, part, role) "
                 "VALUES (1, '김소', 'm1', 'soprano', 'member')")
    conn.execute("INSERT INTO practices (id, title, starts_at, status, closed_at) "
                 "VALUES (1, '정기연습', '2026-07-24T19:00:00', 'closed', "
                 "'2026-07-24T21:00:00')")
    db.upsert_attendance(conn, 1, 1, "late", "버스", "19:30", "member")
    conn.commit()

    store.sync_close(db_path, 1)
    conn2 = db.connect(db_path)
    page_id = conn2.execute(
        "SELECT notion_page_id FROM attendance").fetchone()[0]
    assert page_id is not None
    assert conn2.execute("SELECT notion_synced_at FROM practices "
                         "WHERE id=1").fetchone()[0] is not None

    # 재동기화 — 새 페이지가 아니라 같은 페이지 update
    att_db = setting(conn2, "attendance_db_id")
    before = len(fake.dbs[att_db]["pages"])
    store.sync_close(db_path, 1)
    assert len(fake.dbs[att_db]["pages"]) == before


def test_sync_close_partial_failure_no_duplicates(tmp_path):
    """중간 실패 후 재마감해도 노션 페이지가 중복 생성되지 않는다."""
    import pytest
    conn, fake, store, state = make_env(tmp_path)
    db_path = str(tmp_path / "n.db")
    conn.execute("INSERT INTO members (id, name, student_id, part, role) "
                 "VALUES (1, '김a', 's1', 'soprano', 'member'), "
                 "(2, '김b', 's2', 'alto', 'member')")
    conn.execute("INSERT INTO practices (id, title, starts_at, status, closed_at) "
                 "VALUES (1, 'p', '2026-07-24T19:00:00', 'closed', "
                 "'2026-07-24T21:00:00')")
    db.upsert_attendance(conn, 1, 1, "present", None, None, "member")
    db.upsert_attendance(conn, 1, 2, "present", None, None, "member")
    conn.commit()

    real_create = fake.pages.create
    calls = {"n": 0}

    def flaky_create(**kwargs):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("notion down")
        return real_create(**kwargs)

    fake.pages.create = flaky_create
    with pytest.raises(RuntimeError):
        store.sync_close(db_path, 1)

    fake.pages.create = real_create
    store.sync_close(db_path, 1)  # 재마감(재시도)
    att_db = setting(conn, "attendance_db_id")
    assert len(fake.dbs[att_db]["pages"]) == 2  # 1명당 1페이지, 중복 없음


def test_restore_archive_rebuilds(tmp_path):
    conn, fake, store, state = make_env(tmp_path)
    conn.execute("INSERT INTO members (id, name, student_id, part, role) "
                 "VALUES (1, '김소', 'm1', 'soprano', 'member')")
    conn.commit()
    att_db = setting(conn, "attendance_db_id")
    fake.pages.create(
        parent={"database_id": att_db},
        properties={"이름": title("김소"), "학번": rich("m1"),
                    "파트": select("소프라노"), "연습명": rich("정기연습"),
                    "날짜": date("2026-07-24T19:00:00"),
                    "상태": select("지각"), "사유": rich("버스")})
    store.restore_archive(conn, state)
    p = conn.execute("SELECT * FROM practices").fetchone()
    assert p["status"] == "closed" and p["starts_at"] == "2026-07-24T19:00:00"
    a = conn.execute("SELECT * FROM attendance").fetchone()
    assert a["status"] == "late" and a["reason"] == "버스"
    assert a["notion_page_id"] is not None


def test_restore_archive_normalizes_offset_date(tmp_path):
    conn, fake, store, state = make_env(tmp_path)
    conn.execute("INSERT INTO members (id, name, student_id, part, role) "
                 "VALUES (1, '김소', 'm1', 'soprano', 'member')")
    conn.commit()
    att_db = setting(conn, "attendance_db_id")
    fake.pages.create(
        parent={"database_id": att_db},
        properties={"이름": title("김소"), "학번": rich("m1"),
                    "파트": select("소프라노"), "연습명": rich("정기연습"),
                    "날짜": date("2026-07-24T19:00:00+09:00"),
                    "상태": select("지각"), "사유": rich("버스")})
    store.restore_archive(conn, state)
    p = conn.execute("SELECT * FROM practices").fetchone()
    assert p["starts_at"] == "2026-07-24T19:00:00"


def test_restore_archive_bad_rows_warn_and_skip(tmp_path):
    conn, fake, store, state = make_env(tmp_path)
    conn.execute("INSERT INTO members (id, name, student_id, part, role) "
                 "VALUES (1, '김소', 'm1', 'soprano', 'member')")
    conn.commit()
    att_db = setting(conn, "attendance_db_id")
    # 명단에 없는 학번
    fake.pages.create(
        parent={"database_id": att_db},
        properties={"이름": title("유령"), "학번": rich("ghost"),
                    "파트": select("알토"), "연습명": rich("p"),
                    "날짜": date("2026-07-24T19:00:00"), "상태": select("출석"),
                    "사유": rich("")})
    # 상태 오타
    fake.pages.create(
        parent={"database_id": att_db},
        properties={"이름": title("김소"), "학번": rich("m1"),
                    "파트": select("소프라노"), "연습명": rich("p"),
                    "날짜": date("2026-07-24T19:00:00"), "상태": select("조퇴"),
                    "사유": rich("")})
    store.restore_archive(conn, state)
    assert conn.execute("SELECT COUNT(*) FROM attendance").fetchone()[0] == 0
    assert len(state.roster_warnings) == 2
