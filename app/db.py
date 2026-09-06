import sqlite3
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))
VOCAL_PARTS = ["soprano", "alto", "tenor", "bass"]
PARTS = [*VOCAL_PARTS, "accompanist"]  # 출석 확인 대상 파트
ATTENDEE_FILTER = "role != 'conductor' AND part != 'conductor'"

MEMBERS_SCHEMA = """
CREATE TABLE IF NOT EXISTS members (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  student_id TEXT NOT NULL UNIQUE,
  part TEXT NOT NULL CHECK (part IN
    ('soprano','alto','tenor','bass','accompanist','conductor')),
  role TEXT NOT NULL DEFAULT 'member'
    CHECK (role IN ('member','part_leader','conductor')),
  active INTEGER NOT NULL DEFAULT 1,
  notion_page_id TEXT
);
"""

SCHEMA = MEMBERS_SCHEMA + """
CREATE TABLE IF NOT EXISTS practices (
  id INTEGER PRIMARY KEY,
  title TEXT NOT NULL,
  starts_at TEXT NOT NULL,
  place TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','closed')),
  closed_at TEXT,
  notion_synced_at TEXT
);
CREATE TABLE IF NOT EXISTS attendance (
  id INTEGER PRIMARY KEY,
  practice_id INTEGER NOT NULL REFERENCES practices(id) ON DELETE CASCADE,
  member_id INTEGER NOT NULL REFERENCES members(id),
  status TEXT CHECK (status IN ('present','late','absent')),
  reason TEXT,
  eta TEXT,
  source TEXT NOT NULL
    CHECK (source IN ('member','part_leader','conductor','auto')),
  updated_at TEXT NOT NULL,
  notion_page_id TEXT,
  UNIQUE (practice_id, member_id)
);
CREATE TABLE IF NOT EXISTS part_confirmations (
  practice_id INTEGER NOT NULL REFERENCES practices(id) ON DELETE CASCADE,
  part TEXT NOT NULL,
  confirmed_at TEXT NOT NULL,
  UNIQUE (practice_id, part)
);
CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
"""


def now_kst() -> datetime:
    return datetime.now(KST).replace(tzinfo=None, microsecond=0)


def to_kst_naive_iso(value: str) -> str:
    """ISO datetime string → KST-naive ISO string. Raises ValueError on bad input."""
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is not None:
        dt = dt.astimezone(KST).replace(tzinfo=None)
    return dt.replace(microsecond=0).isoformat()


def connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.executescript(SCHEMA)
    migrate_member_parts(conn)
    return conn


def migrate_member_parts(conn):
    """기존 4파트 DB의 CHECK 제약을 확장하면서 ID·출석 기록을 보존한다."""
    schema = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='members'"
    ).fetchone()[0]
    if "'accompanist'" in schema and "'conductor'" in schema.split("role TEXT")[0]:
        return
    # SQLite CHECK 제약 변경은 테이블 재생성이 필요하다. FK 이름을 그대로 유지한다.
    conn.execute("PRAGMA foreign_keys = OFF")
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(MEMBERS_SCHEMA.replace("members (", "members_expanded ("))
        conn.execute("""
            INSERT INTO members_expanded
                (id, name, student_id, part, role, active, notion_page_id)
            SELECT id, name, student_id,
                   CASE WHEN role='conductor' THEN 'conductor' ELSE part END,
                   role, active, notion_page_id FROM members
        """)
        conn.execute("DROP TABLE members")
        conn.execute("ALTER TABLE members_expanded RENAME TO members")
        if conn.execute("PRAGMA foreign_key_check").fetchone():
            raise sqlite3.IntegrityError("파트 전환 중 출석 참조 오류")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.execute("PRAGMA foreign_keys = ON")


def is_attendee(member):
    return member["role"] != "conductor" and member["part"] != "conductor"


def required_parts(conn):
    """기존 성부 4개 + 활성 반주자가 있는 경우에만 반주자 확인."""
    has_accompanist = conn.execute(
        "SELECT 1 FROM members WHERE active=1 AND part='accompanist' "
        "AND role != 'conductor' LIMIT 1"
    ).fetchone()
    return PARTS.copy() if has_accompanist else VOCAL_PARTS.copy()


def upsert_attendance(conn, practice_id, member_id, status, reason, eta, source):
    conn.execute(
        """INSERT INTO attendance
             (practice_id, member_id, status, reason, eta, source, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT (practice_id, member_id) DO UPDATE SET
             status=excluded.status, reason=excluded.reason, eta=excluded.eta,
             source=excluded.source, updated_at=excluded.updated_at""",
        (practice_id, member_id, status, reason, eta, source,
         now_kst().isoformat()),
    )
