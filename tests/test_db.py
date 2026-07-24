import sqlite3
from datetime import datetime

from app import db


def test_now_kst_is_naive():
    now = db.now_kst()
    assert now.tzinfo is None
    assert now.microsecond == 0


def test_connect_creates_schema(tmp_path):
    conn = db.connect(str(tmp_path / "t.db"))
    tables = {r["name"] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"members", "practices", "attendance", "part_confirmations",
            "settings"} <= tables


def test_attendance_unique_per_member(tmp_path):
    conn = db.connect(str(tmp_path / "t.db"))
    conn.execute("INSERT INTO members (id, name, student_id, part, role) "
                 "VALUES (1, '김a', 's1', 'soprano', 'member')")
    conn.execute("INSERT INTO practices (id, title, starts_at) "
                 "VALUES (1, 'p', '2026-07-24T19:00:00')")
    db.upsert_attendance(conn, 1, 1, "present", None, None, "member")
    db.upsert_attendance(conn, 1, 1, "late", "버스", "19:30", "member")
    rows = conn.execute("SELECT * FROM attendance").fetchall()
    assert len(rows) == 1
    assert rows[0]["status"] == "late"


def test_upsert_preserves_notion_page_id(tmp_path):
    conn = db.connect(str(tmp_path / "t.db"))
    conn.execute("INSERT INTO members (id, name, student_id, part, role) "
                 "VALUES (1, '김a', 's1', 'soprano', 'member')")
    conn.execute("INSERT INTO practices (id, title, starts_at) "
                 "VALUES (1, 'p', '2026-07-24T19:00:00')")
    db.upsert_attendance(conn, 1, 1, "present", None, None, "member")
    conn.execute("UPDATE attendance SET notion_page_id='np1'")
    db.upsert_attendance(conn, 1, 1, "absent", None, None, "conductor")
    assert conn.execute("SELECT notion_page_id FROM attendance").fetchone()[0] == "np1"
