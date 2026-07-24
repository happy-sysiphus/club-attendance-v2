import sqlite3
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))
PARTS = ["soprano", "alto", "tenor", "bass"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS members (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  student_id TEXT NOT NULL UNIQUE,
  part TEXT NOT NULL CHECK (part IN ('soprano','alto','tenor','bass')),
  role TEXT NOT NULL DEFAULT 'member'
    CHECK (role IN ('member','part_leader','conductor')),
  active INTEGER NOT NULL DEFAULT 1,
  notion_page_id TEXT
);
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
    return conn


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
