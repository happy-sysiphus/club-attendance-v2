# 합창단 출석 관리 백엔드 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 스펙(docs/superpowers/specs/2026-07-24-attendance-backend-design.md)의 출석 관리 백엔드를 FastAPI + SQLite + 노션 동기화로 구현한다.

**Architecture:** FastAPI 단일 앱. SQLite는 휘발 작업장(부팅 시 노션에서 복원), 노션이 영구 원본. 자동 결석은 지연 평가(조회 시 계산, 마감 시 확정). 시간대는 KST 나이브 고정.

**Tech Stack:** Python 3.11+, FastAPI, uvicorn, itsdangerous(토큰 서명), notion-client<2.5(구 databases API 고정), sqlite3(stdlib), pytest + httpx(테스트).

## Global Constraints

- 모든 시각은 KST 나이브 `datetime`. DB 저장은 `isoformat()` 문자열(초 단위). 현재 시각은 반드시 `db.now_kst()` 사용 — `datetime.now()` 직접 호출 금지.
- 파트 상수: `PARTS = ["soprano", "alto", "tenor", "bass"]` (db.py에 정의, 전역 유일 정의).
- 역할: `member | part_leader | conductor`. 상태: `present | late | absent | NULL(미확정)`. source: `member | part_leader | conductor | auto`.
- 한국어 표기는 노션 경계(notion.py)에서만 변환: 파트 소프라노/알토/테너/베이스, 역할 단원/파트장/지휘자, 상태 출석/지각/결석.
- pytest는 항상 `--basetemp=.pytest_tmp` 옵션으로 실행.
- `notion-client<2.5` 고정. `# ponytail: 구 databases API(2022-06-28) 고정, 노션 API data_sources 개편 대응 시 2.5+ 마이그레이션` 주석을 requirements.txt에 남긴다.
- HTTP 에러 규약: 인증 실패 401, 권한 위반 403, 없는 리소스 404, 마감 상태 위반·마감 게이트 409, 입력 검증 422.
- 커밋 메시지는 한국어 conventional commit (`feat:`, `test:`, `docs:` …).

## 파일 구조

```text
app/
  __init__.py      # 빈 파일
  config.py        # env 읽기 (NOTION_TOKEN, NOTION_PARENT_PAGE_ID, SECRET_KEY, DB_PATH)
  db.py            # KST 헬퍼, PARTS, 스키마 DDL, connect(), upsert_attendance()
  rules.py         # 순수 함수: 입력 검증, 지연 평가, 출석률
  auth.py          # 토큰 서명/검증 (순수 함수)
  notion.py        # NotionStore: DB 생성·재발견, 명단/기록 복원, 마감 동기화
  main.py          # create_app() + 14개 라우트 + 의존성 + lifespan
tests/
  __init__.py      # 빈 파일 — pytest가 프로젝트 루트를 sys.path에 넣게 함
  conftest.py      # 임시 DB, 시드 명단, app/client 픽스처, login 헬퍼
  fake_notion.py   # notion_client.Client 대역 (dict 기반)
  test_db.py  test_rules.py  test_auth.py  test_practices.py
  test_me.py  test_board.py  test_admin.py  test_close.py
  test_stats.py  test_notion.py  test_restore.py
requirements.txt
README.md
.gitignore
```

---

### Task 1: 스캐폴드 + db.py (스키마·KST 헬퍼)

**Files:**
- Create: `requirements.txt`, `.gitignore`, `app/__init__.py`, `app/config.py`, `app/db.py`, `tests/__init__.py`
- Test: `tests/test_db.py`

**Interfaces:**
- Produces: `db.KST`, `db.PARTS`, `db.now_kst() -> datetime`(나이브 KST, 마이크로초 0), `db.connect(db_path: str) -> sqlite3.Connection`(Row factory, FK on, 스키마 적용), `db.upsert_attendance(conn, practice_id, member_id, status, reason, eta, source)`(notion_page_id 보존), `config.NOTION_TOKEN/NOTION_PARENT_PAGE_ID/SECRET_KEY/DB_PATH`

- [ ] **Step 1: 스캐폴드 파일 작성**

`requirements.txt` (테스트 의존성 포함 — TestClient는 httpx 필수):

```text
fastapi
uvicorn[standard]
itsdangerous
# ponytail: 구 databases API(2022-06-28) 고정, 노션 API data_sources 개편 대응 시 2.5+ 마이그레이션
notion-client<2.5
pytest
httpx
```

`.gitignore`:

```text
__pycache__/
*.db
.pytest_tmp/
.venv/
```

`app/__init__.py`, `tests/__init__.py`: 빈 파일. `tests/__init__.py`는 필수 —
없으면 pytest가 프로젝트 루트를 sys.path에 넣지 않아 `from app import db`와
`from tests.conftest import login` 류 import가 전부 ModuleNotFoundError로 죽는다.

`app/config.py`:

```python
import os

NOTION_TOKEN = os.environ.get("NOTION_TOKEN", "")
NOTION_PARENT_PAGE_ID = os.environ.get("NOTION_PARENT_PAGE_ID", "")
SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret")
DB_PATH = os.environ.get("DB_PATH", "attendance.db")
```

- [ ] **Step 2: 실패하는 테스트 작성**

`tests/test_db.py`:

```python
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
```

- [ ] **Step 3: 실패 확인**

Run: `pytest tests/test_db.py -v --basetemp=.pytest_tmp`
Expected: FAIL (`ModuleNotFoundError` 또는 `AttributeError`)

- [ ] **Step 4: 구현**

`app/db.py`:

```python
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


def connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
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
```

- [ ] **Step 5: 통과 확인**

Run: `pytest tests/test_db.py -v --basetemp=.pytest_tmp`
Expected: 4 PASS

- [ ] **Step 6: 커밋**

```bash
git add requirements.txt .gitignore app/ tests/
git commit -m "feat: 프로젝트 스캐폴드 + SQLite 스키마·KST 헬퍼"
```

---

### Task 2: rules.py — 검증·지연 평가·출석률 (순수 함수)

**Files:**
- Create: `app/rules.py`
- Test: `tests/test_rules.py`

**Interfaces:**
- Produces:
  - `rules.validate_status_input(status: str, reason: str | None, eta: str | None) -> dict` — 정규화된 `{"status", "reason", "eta"}` 반환, 위반 시 `ValueError`
  - `rules.effective_status(status: str | None, source: str | None, starts_at: datetime, now: datetime) -> tuple[str | None, str | None]` — 지연 평가 결과 (status, source)
  - `rules.attendance_rate(present: int, late: int, total: int) -> float` — 소수 3자리

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_rules.py`:

```python
from datetime import datetime

import pytest

from app import rules

START = datetime(2026, 7, 24, 19, 0)


def test_present_drops_extras():
    assert rules.validate_status_input("present", "사유", "19:30") == {
        "status": "present", "reason": None, "eta": None}


def test_late_requires_reason_and_eta():
    with pytest.raises(ValueError):
        rules.validate_status_input("late", None, "19:30")
    with pytest.raises(ValueError):
        rules.validate_status_input("late", "버스", None)
    with pytest.raises(ValueError):
        rules.validate_status_input("late", "버스", "25:99")
    assert rules.validate_status_input("late", "버스", "19:30") == {
        "status": "late", "reason": "버스", "eta": "19:30"}


def test_absent_reason_optional():
    assert rules.validate_status_input("absent", None, None)["reason"] is None
    assert rules.validate_status_input("absent", "시험", "19:30") == {
        "status": "absent", "reason": "시험", "eta": None}


def test_invalid_status_rejected():
    with pytest.raises(ValueError):
        rules.validate_status_input("vacation", None, None)


def test_effective_before_start_stays_null():
    assert rules.effective_status(None, None, START,
                                  datetime(2026, 7, 24, 18, 0)) == (None, None)


def test_effective_after_start_becomes_auto_absent():
    assert rules.effective_status(None, None, START,
                                  datetime(2026, 7, 24, 19, 0)) == ("absent", "auto")


def test_effective_keeps_existing_status():
    assert rules.effective_status("late", "member", START,
                                  datetime(2026, 7, 24, 20, 0)) == ("late", "member")


def test_attendance_rate():
    assert rules.attendance_rate(8, 1, 10) == 0.9
    assert rules.attendance_rate(0, 0, 0) == 0.0
```

- [ ] **Step 2: 실패 확인**

Run: `pytest tests/test_rules.py -v --basetemp=.pytest_tmp`
Expected: FAIL (`ModuleNotFoundError`)

- [ ] **Step 3: 구현**

`app/rules.py`:

```python
import re
from datetime import datetime

ETA_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
STATUSES = {"present", "late", "absent"}


def validate_status_input(status, reason, eta):
    if status not in STATUSES:
        raise ValueError("status는 present/late/absent 중 하나")
    if status == "present":
        return {"status": "present", "reason": None, "eta": None}
    if status == "late":
        if not reason:
            raise ValueError("지각은 사유 필수")
        if not eta or not ETA_RE.match(eta):
            raise ValueError("지각은 예상 도착 시간(HH:MM) 필수")
        return {"status": "late", "reason": reason, "eta": eta}
    return {"status": "absent", "reason": reason or None, "eta": None}


def effective_status(status, source, starts_at: datetime, now: datetime):
    if status is None and now >= starts_at:
        return "absent", "auto"
    return status, source


def attendance_rate(present: int, late: int, total: int) -> float:
    return round((present + late) / total, 3) if total else 0.0
```

- [ ] **Step 4: 통과 확인**

Run: `pytest tests/test_rules.py -v --basetemp=.pytest_tmp`
Expected: 8 PASS

- [ ] **Step 5: 커밋**

```bash
git add app/rules.py tests/test_rules.py
git commit -m "feat: 출석 규칙 순수 함수 — 입력 검증·지연 평가·출석률"
```

---

### Task 3: auth.py + create_app 뼈대 + 로그인/헬스

**Files:**
- Create: `app/auth.py`, `app/main.py`, `tests/conftest.py`
- Test: `tests/test_auth.py`

**Interfaces:**
- Consumes: `db.connect`, `config.SECRET_KEY`
- Produces:
  - `auth.sign_token(member_id: int, secret: str) -> str`, `auth.verify_token(token: str, secret: str) -> int | None`
  - `main.create_app(db_path: str, notion=None) -> FastAPI` — `app.state.db_path`, `app.state.conn`, `app.state.notion`, `app.state.roster_warnings: list[str]` 보유
  - main.py 의존성(이후 태스크가 사용): `get_conn(request) -> sqlite3.Connection`, `current_member(request) -> sqlite3.Row`(401), `require_conductor(member) -> sqlite3.Row`(403), `require_staff(member) -> sqlite3.Row`(파트장·지휘자, 403)
  - 라우트: `POST /auth/login`, `GET /health`
  - conftest 픽스처(이후 모든 테스트가 사용): `app`, `client`, `conn`, 헬퍼 `login(client, name, student_id)`, 모듈 상수 `SEED`(Task 11 테스트가 import); 시드 명단 — 지휘자 `("지휘자", "c1", "soprano", "conductor")`, 파트장 4명 `("파트장소프라노", "ps", "soprano")` … `("파트장베이스", "pb", "bass")`, 단원 `("김소", "m1", "soprano")`, `("김알", "m2", "alto")`

- [ ] **Step 1: conftest 작성**

`tests/conftest.py`:

```python
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
```

- [ ] **Step 2: 실패하는 테스트 작성**

`tests/test_auth.py`:

```python
import pytest

from app import auth
from tests.conftest import login


def test_token_roundtrip():
    t = auth.sign_token(7, "s")
    assert auth.verify_token(t, "s") == 7
    assert auth.verify_token(t, "other") is None
    assert auth.verify_token("garbage", "s") is None


def test_health(client):
    assert client.get("/health").json() == {"ok": True}


def test_login_success_sets_cookie(client):
    body = login(client, "김소", "m1")
    assert body["role"] == "member" and body["part"] == "soprano"
    assert "session" in client.cookies


def test_login_wrong_name_401(client):
    r = client.post("/auth/login", json={"name": "김수", "student_id": "m1"})
    assert r.status_code == 401


def test_login_inactive_member_401(client, conn):
    conn.execute("UPDATE members SET active=0 WHERE student_id='m1'")
    conn.commit()
    r = client.post("/auth/login", json={"name": "김소", "student_id": "m1"})
    assert r.status_code == 401


@pytest.mark.xfail(reason="Task 4에서 /practices 라우트 추가")
def test_protected_route_without_cookie_401(client):
    assert client.get("/practices").status_code == 401
```

- [ ] **Step 3: 실패 확인**

Run: `pytest tests/test_auth.py -v --basetemp=.pytest_tmp`
Expected: FAIL (`ImportError: create_app`)

- [ ] **Step 4: 구현**

`app/auth.py`:

```python
from itsdangerous import BadSignature, URLSafeSerializer


def sign_token(member_id: int, secret: str) -> str:
    return URLSafeSerializer(secret).dumps({"m": member_id})


def verify_token(token: str, secret: str):
    try:
        return URLSafeSerializer(secret).loads(token)["m"]
    except (BadSignature, KeyError, TypeError):
        return None
```

`app/main.py`:

```python
import sqlite3

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from pydantic import BaseModel

from . import auth, config, db, rules


def get_conn(request: Request) -> sqlite3.Connection:
    return request.app.state.conn


def current_member(request: Request,
                   conn: sqlite3.Connection = Depends(get_conn)) -> sqlite3.Row:
    token = request.cookies.get("session")
    member_id = auth.verify_token(token, config.SECRET_KEY) if token else None
    if member_id is None:
        raise HTTPException(401, "로그인 필요")
    row = conn.execute(
        "SELECT * FROM members WHERE id=? AND active=1", (member_id,)).fetchone()
    if row is None:
        raise HTTPException(401, "로그인 필요")
    return row


def require_conductor(member=Depends(current_member)) -> sqlite3.Row:
    if member["role"] != "conductor":
        raise HTTPException(403, "지휘자만 가능")
    return member


def require_staff(member=Depends(current_member)) -> sqlite3.Row:
    if member["role"] not in ("part_leader", "conductor"):
        raise HTTPException(403, "파트장·지휘자만 가능")
    return member


class LoginIn(BaseModel):
    name: str
    student_id: str


def create_app(db_path: str, notion=None) -> FastAPI:
    app = FastAPI()
    app.state.db_path = db_path
    app.state.conn = db.connect(db_path)
    app.state.notion = notion
    app.state.roster_warnings = []

    @app.get("/health")
    def health():
        return {"ok": True}

    @app.post("/auth/login")
    def login(body: LoginIn, response: Response, request: Request):
        conn = request.app.state.conn

        def find():
            return conn.execute(
                "SELECT * FROM members WHERE student_id=? AND name=? AND active=1",
                (body.student_id.strip(), body.name.strip())).fetchone()

        row = find()
        if row is None and request.app.state.notion is not None:
            # 명단 캐시 미스 → 노션에서 갱신 후 1회 재시도 (Task 11에서 연결)
            request.app.state.notion.refresh_roster(conn, request.app.state)
            row = find()
        if row is None:
            raise HTTPException(401, "명단에 없음")
        response.set_cookie("session",
                            auth.sign_token(row["id"], config.SECRET_KEY),
                            httponly=True, max_age=60 * 60 * 24 * 180)
        return {"member_id": row["id"], "name": row["name"],
                "part": row["part"], "role": row["role"]}

    register_routes(app)
    return app


def register_routes(app: FastAPI) -> None:
    """Task 4~9에서 라우트를 이 함수 안에 추가한다."""


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(create_app(config.DB_PATH), host="0.0.0.0", port=8000)
```

주의: `test_protected_route_without_cookie_401`은 Task 4에서 `GET /practices`가 생기기 전까지 404가 떠서 Step 2 코드에 이미 xfail 마커가 붙어 있다. Task 4에서 마커(그리고 더 이상 안 쓰이면 `import pytest`)를 제거한다.

- [ ] **Step 5: 통과 확인**

Run: `pytest tests/test_auth.py -v --basetemp=.pytest_tmp`
Expected: 5 PASS, 1 XFAIL

- [ ] **Step 6: 커밋**

```bash
git add app/auth.py app/main.py tests/conftest.py tests/test_auth.py
git commit -m "feat: 이름+학번 로그인, 서명 쿠키, 역할 의존성"
```

---

### Task 4: 연습 CRUD

**Files:**
- Modify: `app/main.py` (`register_routes` 내부)
- Test: `tests/test_practices.py`

**Interfaces:**
- Consumes: `require_conductor`, `current_member`, `get_conn`, `db.now_kst`
- Produces:
  - `POST /practices` (지휘자) body `{"title", "starts_at": "YYYY-MM-DDTHH:MM:SS", "place"?}` → 201 `{"id", ...행 전체}`
  - `GET /practices` (전 역할) → starts_at 내림차순 목록
  - `PUT /practices/{pid}` (지휘자, open만) / `DELETE /practices/{pid}` (지휘자, open만) → 마감 상태 위반 시 409
  - main.py 헬퍼 `get_practice(conn, pid) -> sqlite3.Row`(404) — 이후 태스크가 사용

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_practices.py`:

```python
from tests.conftest import login

BODY = {"title": "정기연습", "starts_at": "2026-09-01T19:00:00", "place": "음악관"}


def test_conductor_creates_practice(client):
    login(client, "지휘자", "c1")
    r = client.post("/practices", json=BODY)
    assert r.status_code == 201
    assert r.json()["status"] == "open"


def test_member_cannot_create(client):
    login(client, "김소", "m1")
    assert client.post("/practices", json=BODY).status_code == 403


def test_bad_starts_at_422(client):
    login(client, "지휘자", "c1")
    r = client.post("/practices", json={"title": "x", "starts_at": "내일저녁"})
    assert r.status_code == 422


def test_list_visible_to_member(client):
    login(client, "지휘자", "c1")
    client.post("/practices", json=BODY)
    login(client, "김소", "m1")
    r = client.get("/practices")
    assert r.status_code == 200 and len(r.json()) == 1


def test_update_and_delete_open_only(client, conn):
    login(client, "지휘자", "c1")
    pid = client.post("/practices", json=BODY).json()["id"]
    r = client.put(f"/practices/{pid}", json={**BODY, "place": "대강당"})
    assert r.status_code == 200 and r.json()["place"] == "대강당"
    conn.execute("UPDATE practices SET status='closed' WHERE id=?", (pid,))
    conn.commit()
    assert client.put(f"/practices/{pid}", json=BODY).status_code == 409
    assert client.delete(f"/practices/{pid}").status_code == 409
    conn.execute("UPDATE practices SET status='open' WHERE id=?", (pid,))
    conn.commit()
    assert client.delete(f"/practices/{pid}").status_code == 200
    assert client.get("/practices").json() == []
```

- [ ] **Step 2: 실패 확인**

Run: `pytest tests/test_practices.py -v --basetemp=.pytest_tmp`
Expected: FAIL (404 — 라우트 없음)

- [ ] **Step 3: 구현**

`app/main.py`의 `register_routes` 안에 추가 (모듈 상단에 `from datetime import datetime` 추가):

```python
class PracticeIn(BaseModel):
    title: str
    starts_at: str
    place: str = ""


def parse_starts_at(value: str) -> str:
    try:
        return datetime.fromisoformat(value).isoformat()
    except ValueError:
        raise HTTPException(422, "starts_at는 ISO 형식(YYYY-MM-DDTHH:MM:SS)")


def get_practice(conn, pid: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM practices WHERE id=?", (pid,)).fetchone()
    if row is None:
        raise HTTPException(404, "연습 없음")
    return row


def practice_dict(row: sqlite3.Row) -> dict:
    return dict(row)


def register_routes(app: FastAPI) -> None:
    @app.post("/practices", status_code=201)
    def create_practice(body: PracticeIn, conn=Depends(get_conn),
                        _=Depends(require_conductor)):
        if not body.title.strip():
            raise HTTPException(422, "title 필수")
        cur = conn.execute(
            "INSERT INTO practices (title, starts_at, place) VALUES (?,?,?)",
            (body.title.strip(), parse_starts_at(body.starts_at), body.place))
        conn.commit()
        return practice_dict(get_practice(conn, cur.lastrowid))

    @app.get("/practices")
    def list_practices(conn=Depends(get_conn), _=Depends(current_member)):
        rows = conn.execute(
            "SELECT * FROM practices ORDER BY starts_at DESC").fetchall()
        return [practice_dict(r) for r in rows]

    @app.put("/practices/{pid}")
    def update_practice(pid: int, body: PracticeIn, conn=Depends(get_conn),
                        _=Depends(require_conductor)):
        if get_practice(conn, pid)["status"] != "open":
            raise HTTPException(409, "마감된 연습")
        conn.execute(
            "UPDATE practices SET title=?, starts_at=?, place=? WHERE id=?",
            (body.title.strip(), parse_starts_at(body.starts_at), body.place, pid))
        conn.commit()
        return practice_dict(get_practice(conn, pid))

    @app.delete("/practices/{pid}")
    def delete_practice(pid: int, conn=Depends(get_conn),
                        _=Depends(require_conductor)):
        if get_practice(conn, pid)["status"] != "open":
            raise HTTPException(409, "마감된 연습은 삭제 불가")
        conn.execute("DELETE FROM practices WHERE id=?", (pid,))
        conn.commit()
        return {"deleted": pid}
```

`tests/test_auth.py`의 xfail 마커와 `import pytest` 제거.

- [ ] **Step 4: 통과 확인**

Run: `pytest tests/ -v --basetemp=.pytest_tmp`
Expected: 전부 PASS (xfail 없이)

- [ ] **Step 5: 커밋**

```bash
git add app/main.py tests/test_practices.py tests/test_auth.py
git commit -m "feat: 연습 CRUD — 지휘자 전용 쓰기, open 상태 제약"
```

---

### Task 5: 본인 입력 — GET/PUT /practices/{pid}/me

**Files:**
- Modify: `app/main.py` (`register_routes` 내부)
- Test: `tests/test_me.py`

**Interfaces:**
- Consumes: `rules.validate_status_input`, `rules.effective_status`, `db.upsert_attendance`, `db.now_kst`, `get_practice`
- Produces:
  - `GET /practices/{pid}/me` → `{"status", "source", "reason", "eta"}` (지연 평가 반영)
  - `PUT /practices/{pid}/me` body `{"status", "reason"?, "eta"?}` — starts_at 전 + open만, 위반 시 403(시간)·409(마감)·422(검증)
  - main.py **모듈 레벨** 헬퍼 `effective_row(att_row | None, practice_row) -> dict` — board(Task 6)·admin(Task 7)도 사용. 반환: `{"status", "source", "reason", "eta"}`
  - 테스트 공용 계약: `tests/test_me.py`의 `make_practice(client, body) -> practice_id` 헬퍼와 상수 `FUTURE`/`PAST` — Task 6·7·8·9 테스트가 `from tests.test_me import make_practice, FUTURE, PAST`로 재사용. 이름·시그니처 변경 금지

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_me.py`:

```python
from tests.conftest import login

FUTURE = {"title": "p", "starts_at": "2099-01-01T19:00:00"}
PAST = {"title": "p", "starts_at": "2000-01-01T19:00:00"}


def make_practice(client, body):
    login(client, "지휘자", "c1")
    return client.post("/practices", json=body).json()["id"]


def test_me_default_unconfirmed(client):
    pid = make_practice(client, FUTURE)
    login(client, "김소", "m1")
    assert client.get(f"/practices/{pid}/me").json() == {
        "status": None, "source": None, "reason": None, "eta": None}


def test_me_put_late_and_read_back(client):
    pid = make_practice(client, FUTURE)
    login(client, "김소", "m1")
    r = client.put(f"/practices/{pid}/me",
                   json={"status": "late", "reason": "버스", "eta": "19:30"})
    assert r.status_code == 200
    body = client.get(f"/practices/{pid}/me").json()
    assert body["status"] == "late" and body["source"] == "member"


def test_me_put_late_without_reason_422(client):
    pid = make_practice(client, FUTURE)
    login(client, "김소", "m1")
    r = client.put(f"/practices/{pid}/me", json={"status": "late", "eta": "19:30"})
    assert r.status_code == 422


def test_me_locked_after_start(client):
    pid = make_practice(client, PAST)
    login(client, "김소", "m1")
    r = client.put(f"/practices/{pid}/me", json={"status": "present"})
    assert r.status_code == 403


def test_me_shows_auto_absent_after_start(client, conn):
    pid = make_practice(client, PAST)
    login(client, "김소", "m1")
    body = client.get(f"/practices/{pid}/me").json()
    assert body["status"] == "absent" and body["source"] == "auto"
    # 지연 평가 핵심 계약: 표시만 absent, DB에는 아직 아무 행도 확정 안 됨
    assert conn.execute("SELECT COUNT(*) FROM attendance WHERE practice_id=?",
                        (pid,)).fetchone()[0] == 0


def test_me_locked_when_closed(client, conn):
    pid = make_practice(client, FUTURE)
    conn.execute("UPDATE practices SET status='closed' WHERE id=?", (pid,))
    conn.commit()
    login(client, "김소", "m1")
    r = client.put(f"/practices/{pid}/me", json={"status": "present"})
    assert r.status_code == 409
```

- [ ] **Step 2: 실패 확인**

Run: `pytest tests/test_me.py -v --basetemp=.pytest_tmp`
Expected: FAIL (404)

- [ ] **Step 3: 구현**

모듈 상단에 `class StatusIn(BaseModel): status: str; reason: str | None = None; eta: str | None = None` 정의. `effective_row`는 `get_practice` 옆 **모듈 레벨**에 정의:

```python
def effective_row(att, practice) -> dict:
    starts_at = datetime.fromisoformat(practice["starts_at"])
    raw = (att["status"], att["source"]) if att else (None, None)
    status, source = rules.effective_status(raw[0], raw[1], starts_at, db.now_kst())
    return {"status": status, "source": source,
            "reason": att["reason"] if att else None,
            "eta": att["eta"] if att else None}
```

라우트 두 개는 `register_routes` 안에 추가:

```python
    @app.get("/practices/{pid}/me")
    def my_status(pid: int, conn=Depends(get_conn), me=Depends(current_member)):
        practice = get_practice(conn, pid)
        att = conn.execute(
            "SELECT * FROM attendance WHERE practice_id=? AND member_id=?",
            (pid, me["id"])).fetchone()
        return effective_row(att, practice)

    @app.put("/practices/{pid}/me")
    def set_my_status(pid: int, body: StatusIn, conn=Depends(get_conn),
                      me=Depends(current_member)):
        practice = get_practice(conn, pid)
        if practice["status"] != "open":
            raise HTTPException(409, "마감된 연습")
        if db.now_kst() >= datetime.fromisoformat(practice["starts_at"]):
            raise HTTPException(403, "연습 시작 후에는 파트장·지휘자만 수정 가능")
        try:
            v = rules.validate_status_input(body.status, body.reason, body.eta)
        except ValueError as e:
            raise HTTPException(422, str(e))
        db.upsert_attendance(conn, pid, me["id"],
                             v["status"], v["reason"], v["eta"], "member")
        conn.commit()
        return effective_row(conn.execute(
            "SELECT * FROM attendance WHERE practice_id=? AND member_id=?",
            (pid, me["id"])).fetchone(), practice)
```

- [ ] **Step 4: 통과 확인**

Run: `pytest tests/test_me.py -v --basetemp=.pytest_tmp`
Expected: 6 PASS

- [ ] **Step 5: 커밋**

```bash
git add app/main.py tests/test_me.py
git commit -m "feat: 단원 본인 예정 상태 입력 — 시작 전 시간창, 지연 평가 조회"
```

---

### Task 6: 현황판 — GET /practices/{pid}/board

**Files:**
- Modify: `app/main.py` (`register_routes` 내부)
- Test: `tests/test_board.py`

**Interfaces:**
- Consumes: `require_staff`, `effective_row`, `db.PARTS`
- Produces: `GET /practices/{pid}/board` →

```json
{
  "practice": {"id": 1, "title": "…", "starts_at": "…", "place": "…",
               "status": "open", "notion_synced_at": null},
  "parts": {
    "soprano": {
      "confirmed": false,
      "counts": {"present": 0, "late": 0, "absent": 0, "unconfirmed": 0},
      "members": [{"member_id": 1, "name": "김소", "status": null,
                   "source": null, "reason": null, "eta": null}]
    }
  },
  "totals": {"present": 0, "late": 0, "absent": 0, "unconfirmed": 0},
  "roster_warnings": []
}
```

파트장 → `parts`에 자기 파트 키만, `roster_warnings`는 **키 유지 + 항상 빈 배열 `[]`**. 지휘자 → 4파트 전체 + `app.state.roster_warnings` 내용. 단원 → 403. `counts`의 `unconfirmed`는 지연 평가 후 status가 None인 인원.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_board.py`:

```python
from tests.conftest import login
from tests.test_me import make_practice, FUTURE, PAST


def test_member_gets_403(client):
    pid = make_practice(client, FUTURE)
    login(client, "김소", "m1")
    assert client.get(f"/practices/{pid}/board").status_code == 403


def test_part_leader_sees_only_own_part(client):
    pid = make_practice(client, FUTURE)
    login(client, "파트장알토", "pa")
    body = client.get(f"/practices/{pid}/board").json()
    assert list(body["parts"].keys()) == ["alto"]
    names = [m["name"] for m in body["parts"]["alto"]["members"]]
    assert "김알" in names and "김소" not in names


def test_conductor_sees_all_parts_and_totals(client):
    pid = make_practice(client, FUTURE)
    login(client, "김소", "m1")
    client.put(f"/practices/{pid}/me",
               json={"status": "late", "reason": "버스", "eta": "19:30"})
    login(client, "지휘자", "c1")
    body = client.get(f"/practices/{pid}/board").json()
    assert set(body["parts"]) == {"soprano", "alto", "tenor", "bass"}
    assert body["totals"]["late"] == 1
    # 시드 7명: late 1 + 미확정 6 (시작 전이라 unconfirmed)
    assert body["totals"]["unconfirmed"] == 6


def test_auto_absent_counted_after_start(client):
    pid = make_practice(client, PAST)
    login(client, "지휘자", "c1")
    body = client.get(f"/practices/{pid}/board").json()
    assert body["totals"]["absent"] == 7
    assert body["totals"]["unconfirmed"] == 0
    soprano = body["parts"]["soprano"]["members"]
    assert all(m["status"] == "absent" and m["source"] == "auto"
               for m in soprano)


def test_inactive_member_excluded(client, conn):
    conn.execute("UPDATE members SET active=0 WHERE student_id='m2'")
    conn.commit()
    pid = make_practice(client, FUTURE)
    login(client, "지휘자", "c1")
    body = client.get(f"/practices/{pid}/board").json()
    names = [m["name"] for m in body["parts"]["alto"]["members"]]
    assert "김알" not in names


def test_confirmed_flag_flips_after_confirm(client):
    pid = make_practice(client, FUTURE)
    login(client, "파트장테너", "pt")
    client.post(f"/practices/{pid}/part/confirm", json={"part": "tenor"})
    body = client.get(f"/practices/{pid}/board").json()
    assert body["parts"]["tenor"]["confirmed"] is True


def test_roster_warnings_conductor_only(client, app):
    app.state.roster_warnings[:] = ["명단 3행 파트 오타"]
    pid = make_practice(client, FUTURE)
    login(client, "지휘자", "c1")
    assert client.get(f"/practices/{pid}/board").json()[
        "roster_warnings"] == ["명단 3행 파트 오타"]
    login(client, "파트장알토", "pa")
    assert client.get(f"/practices/{pid}/board").json()["roster_warnings"] == []
```

주의: `test_confirmed_flag_flips_after_confirm`은 Task 7의 `/part/confirm`이 필요하다 — Task 6 시점에는 `@pytest.mark.xfail(reason="Task 7에서 confirm 라우트 추가")`(파일 상단 `import pytest`)로 표시하고 Task 7에서 마커를 제거한다.

- [ ] **Step 2: 실패 확인**

Run: `pytest tests/test_board.py -v --basetemp=.pytest_tmp`
Expected: FAIL (404)

- [ ] **Step 3: 구현**

`register_routes` 안에 추가:

```python
    @app.get("/practices/{pid}/board")
    def board(pid: int, request: Request, conn=Depends(get_conn),
              me=Depends(require_staff)):
        practice = get_practice(conn, pid)
        visible = db.PARTS if me["role"] == "conductor" else [me["part"]]
        confirmed = {r["part"] for r in conn.execute(
            "SELECT part FROM part_confirmations WHERE practice_id=?", (pid,))}
        att_by_member = {r["member_id"]: r for r in conn.execute(
            "SELECT * FROM attendance WHERE practice_id=?", (pid,))}
        parts, totals = {}, {"present": 0, "late": 0, "absent": 0, "unconfirmed": 0}
        for part in visible:
            members, counts = [], {"present": 0, "late": 0, "absent": 0,
                                   "unconfirmed": 0}
            rows = conn.execute(
                "SELECT * FROM members WHERE part=? AND active=1 ORDER BY name",
                (part,)).fetchall()
            for m in rows:
                eff = effective_row(att_by_member.get(m["id"]), practice)
                counts[eff["status"] or "unconfirmed"] += 1
                members.append({"member_id": m["id"], "name": m["name"], **eff})
            for k in totals:
                totals[k] += counts[k]
            parts[part] = {"confirmed": part in confirmed,
                           "counts": counts, "members": members}
        return {"practice": {"id": practice["id"], "title": practice["title"],
                             "starts_at": practice["starts_at"],
                             "place": practice["place"],
                             "status": practice["status"],
                             "notion_synced_at": practice["notion_synced_at"]},
                "parts": parts, "totals": totals,
                "roster_warnings": (request.app.state.roster_warnings
                                    if me["role"] == "conductor" else [])}
```

- [ ] **Step 4: 통과 확인**

Run: `pytest tests/test_board.py -v --basetemp=.pytest_tmp`
Expected: 6 PASS, 1 XFAIL

- [ ] **Step 5: 커밋**

```bash
git add app/main.py tests/test_board.py
git commit -m "feat: 현황판 — 역할별 범위, 파트별 집계, 자동 결석 표시"
```

---

### Task 7: 관리자 수정 + 파트 확인

**Files:**
- Modify: `app/main.py` (`register_routes` 내부)
- Test: `tests/test_admin.py`

**Interfaces:**
- Consumes: `require_staff`, `rules.validate_status_input`, `db.upsert_attendance`, `StatusIn`
- Produces:
  - `PUT /practices/{pid}/members/{member_id}` body `StatusIn` — 파트장: 자기 파트만(403), 지휘자: 전체. open만(409). source는 수정자 역할.
  - `POST /practices/{pid}/part/confirm` body `{"part": "soprano"}` — 파트장: 자기 파트만(403), 지휘자: 임의 파트. 멱등(중복 확인 OK). 잘못된 파트명 422.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_admin.py`:

```python
from tests.conftest import login
from tests.test_me import make_practice, FUTURE, PAST


def member_id_of(conn, student_id):
    return conn.execute("SELECT id FROM members WHERE student_id=?",
                        (student_id,)).fetchone()["id"]


def test_part_leader_edits_own_part_after_start(client, conn):
    pid = make_practice(client, PAST)
    mid = member_id_of(conn, "m1")
    login(client, "파트장소프라노", "ps")
    r = client.put(f"/practices/{pid}/members/{mid}",
                   json={"status": "late", "reason": "늦잠", "eta": "19:40"})
    assert r.status_code == 200
    assert r.json()["status"] == "late" and r.json()["source"] == "part_leader"


def test_part_leader_cannot_edit_other_part(client, conn):
    pid = make_practice(client, FUTURE)
    mid = member_id_of(conn, "m2")  # alto
    login(client, "파트장소프라노", "ps")
    r = client.put(f"/practices/{pid}/members/{mid}", json={"status": "present"})
    assert r.status_code == 403


def test_conductor_edits_anyone(client, conn):
    pid = make_practice(client, FUTURE)
    mid = member_id_of(conn, "m2")
    login(client, "지휘자", "c1")
    r = client.put(f"/practices/{pid}/members/{mid}", json={"status": "present"})
    assert r.status_code == 200 and r.json()["source"] == "conductor"


def test_member_cannot_use_admin_endpoint(client, conn):
    pid = make_practice(client, FUTURE)
    mid = member_id_of(conn, "m1")
    login(client, "김소", "m1")
    r = client.put(f"/practices/{pid}/members/{mid}", json={"status": "present"})
    assert r.status_code == 403


def test_edit_locked_when_closed(client, conn):
    pid = make_practice(client, FUTURE)
    mid = member_id_of(conn, "m1")
    conn.execute("UPDATE practices SET status='closed' WHERE id=?", (pid,))
    conn.commit()
    login(client, "지휘자", "c1")
    r = client.put(f"/practices/{pid}/members/{mid}", json={"status": "present"})
    assert r.status_code == 409


def test_confirm_own_part_idempotent(client):
    pid = make_practice(client, FUTURE)
    login(client, "파트장테너", "pt")
    assert client.post(f"/practices/{pid}/part/confirm",
                       json={"part": "tenor"}).status_code == 200
    assert client.post(f"/practices/{pid}/part/confirm",
                       json={"part": "tenor"}).status_code == 200


def test_confirm_other_part_403_but_conductor_ok(client):
    pid = make_practice(client, FUTURE)
    login(client, "파트장테너", "pt")
    assert client.post(f"/practices/{pid}/part/confirm",
                       json={"part": "bass"}).status_code == 403
    login(client, "지휘자", "c1")
    assert client.post(f"/practices/{pid}/part/confirm",
                       json={"part": "bass"}).status_code == 200


def test_confirm_bad_part_422(client):
    pid = make_practice(client, FUTURE)
    login(client, "지휘자", "c1")
    assert client.post(f"/practices/{pid}/part/confirm",
                       json={"part": "baritone"}).status_code == 422
```

- [ ] **Step 2: 실패 확인**

Run: `pytest tests/test_admin.py -v --basetemp=.pytest_tmp`
Expected: FAIL (404)

- [ ] **Step 3: 구현**

`register_routes` 안에 추가 (모듈 상단 `class PartIn(BaseModel): part: str`):

```python
    @app.put("/practices/{pid}/members/{member_id}")
    def set_member_status(pid: int, member_id: int, body: StatusIn,
                          conn=Depends(get_conn), me=Depends(require_staff)):
        practice = get_practice(conn, pid)
        if practice["status"] != "open":
            raise HTTPException(409, "마감된 연습")
        target = conn.execute(
            "SELECT * FROM members WHERE id=? AND active=1",
            (member_id,)).fetchone()
        if target is None:
            raise HTTPException(404, "단원 없음")
        if me["role"] == "part_leader" and target["part"] != me["part"]:
            raise HTTPException(403, "자기 파트만 수정 가능")
        try:
            v = rules.validate_status_input(body.status, body.reason, body.eta)
        except ValueError as e:
            raise HTTPException(422, str(e))
        db.upsert_attendance(conn, pid, member_id,
                             v["status"], v["reason"], v["eta"], me["role"])
        conn.commit()
        return effective_row(conn.execute(
            "SELECT * FROM attendance WHERE practice_id=? AND member_id=?",
            (pid, member_id)).fetchone(), practice)

    @app.post("/practices/{pid}/part/confirm")
    def confirm_part(pid: int, body: PartIn, conn=Depends(get_conn),
                     me=Depends(require_staff)):
        get_practice(conn, pid)
        if body.part not in db.PARTS:
            raise HTTPException(422, "part는 soprano/alto/tenor/bass 중 하나")
        if me["role"] == "part_leader" and body.part != me["part"]:
            raise HTTPException(403, "자기 파트만 확인 가능")
        conn.execute(
            """INSERT INTO part_confirmations (practice_id, part, confirmed_at)
               VALUES (?, ?, ?)
               ON CONFLICT (practice_id, part) DO NOTHING""",
            (pid, body.part, db.now_kst().isoformat()))
        conn.commit()
        return {"practice_id": pid, "part": body.part, "confirmed": True}
```

`tests/test_board.py`의 `test_confirmed_flag_flips_after_confirm`에서 xfail 마커(그리고 더 이상 안 쓰이면 `import pytest`) 제거.

- [ ] **Step 4: 통과 확인**

Run: `pytest tests/ -v --basetemp=.pytest_tmp`
Expected: 전부 PASS (test_admin.py 8개 + test_board.py xfail 해제분 포함)

- [ ] **Step 5: 커밋**

```bash
git add app/main.py tests/test_admin.py tests/test_board.py
git commit -m "feat: 파트장·지휘자 상태 수정, 파트 확인 완료(지휘자 대행 포함)"
```

---

### Task 8: 마감·재오픈

**Files:**
- Modify: `app/main.py` (`register_routes` 내부)
- Test: `tests/test_close.py`

**Interfaces:**
- Consumes: `require_conductor`, `db.upsert_attendance`, `db.PARTS`, `get_practice`
- Produces:
  - `POST /practices/{pid}/close` (지휘자) — open이면: 4파트 확인 게이트(미달 시 409 `{"detail": {"missing_parts": [...]}}`) → 미확정 전원 `absent/auto` 확정 + 전 활성 단원 행 보장 → `status=closed`. closed면: 게이트 생략(멱등 재동기화 경로). 마지막에 노션 스토어 있으면 `BackgroundTasks`로 `notion.sync_close(db_path, pid)` 예약. → `{"status": "closed"}`
  - `POST /practices/{pid}/reopen` (지휘자) — `status=open`, part_confirmations 유지. → `{"status": "open"}`
  - 테스트 헬퍼 `confirm_all_parts(client, pid)` — Task 9·11 테스트가 재사용

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_close.py`:

```python
from app import db
from tests.conftest import login
from tests.test_me import make_practice, FUTURE, PAST


def confirm_all_parts(client, pid):
    login(client, "지휘자", "c1")
    for part in db.PARTS:
        assert client.post(f"/practices/{pid}/part/confirm",
                           json={"part": part}).status_code == 200


def test_close_blocked_until_all_parts_confirmed(client):
    pid = make_practice(client, PAST)
    login(client, "지휘자", "c1")
    r = client.post(f"/practices/{pid}/close")
    assert r.status_code == 409
    assert set(r.json()["detail"]["missing_parts"]) == set(db.PARTS)


def test_close_materializes_auto_absent(client, conn):
    pid = make_practice(client, PAST)
    confirm_all_parts(client, pid)
    assert client.post(f"/practices/{pid}/close").status_code == 200
    rows = conn.execute(
        "SELECT status, source FROM attendance WHERE practice_id=?",
        (pid,)).fetchall()
    assert len(rows) == 7  # 시드 전원 행 생성
    assert all(r["status"] == "absent" and r["source"] == "auto" for r in rows)
    p = conn.execute("SELECT * FROM practices WHERE id=?", (pid,)).fetchone()
    assert p["status"] == "closed" and p["closed_at"] is not None


def test_close_excludes_inactive_members(client, conn):
    conn.execute("UPDATE members SET active=0 WHERE student_id='m2'")
    conn.commit()
    pid = make_practice(client, PAST)
    confirm_all_parts(client, pid)
    client.post(f"/practices/{pid}/close")
    assert conn.execute(
        "SELECT COUNT(*) FROM attendance WHERE practice_id=?",
        (pid,)).fetchone()[0] == 6  # 활성 6명만 확정


def test_close_keeps_entered_statuses(client, conn):
    pid = make_practice(client, FUTURE)
    login(client, "김소", "m1")
    client.put(f"/practices/{pid}/me",
               json={"status": "late", "reason": "버스", "eta": "19:30"})
    confirm_all_parts(client, pid)
    client.post(f"/practices/{pid}/close")
    row = conn.execute(
        "SELECT a.status, a.source FROM attendance a JOIN members m "
        "ON m.id=a.member_id WHERE a.practice_id=? AND m.student_id='m1'",
        (pid,)).fetchone()
    assert row["status"] == "late" and row["source"] == "member"


def test_close_idempotent(client):
    pid = make_practice(client, PAST)
    confirm_all_parts(client, pid)
    assert client.post(f"/practices/{pid}/close").status_code == 200
    assert client.post(f"/practices/{pid}/close").status_code == 200


def test_reopen_keeps_confirmations_then_reclose(client, conn):
    pid = make_practice(client, PAST)
    confirm_all_parts(client, pid)
    client.post(f"/practices/{pid}/close")
    assert client.post(f"/practices/{pid}/reopen").json()["status"] == "open"
    n = conn.execute("SELECT COUNT(*) FROM part_confirmations "
                     "WHERE practice_id=?", (pid,)).fetchone()[0]
    assert n == 4
    # 재오픈 후 즉시 재마감 가능 (확인 유지 덕분)
    assert client.post(f"/practices/{pid}/close").status_code == 200


def test_reopen_requires_conductor(client):
    pid = make_practice(client, PAST)
    confirm_all_parts(client, pid)
    client.post(f"/practices/{pid}/close")
    login(client, "파트장소프라노", "ps")
    assert client.post(f"/practices/{pid}/reopen").status_code == 403
```

- [ ] **Step 2: 실패 확인**

Run: `pytest tests/test_close.py -v --basetemp=.pytest_tmp`
Expected: FAIL (404)

- [ ] **Step 3: 구현**

`register_routes` 안에 추가 (모듈 상단 `from fastapi import BackgroundTasks` 추가):

```python
    @app.post("/practices/{pid}/close")
    def close_practice(pid: int, bg: BackgroundTasks, request: Request,
                       conn=Depends(get_conn), _=Depends(require_conductor)):
        practice = get_practice(conn, pid)
        if practice["status"] == "open":
            confirmed = {r["part"] for r in conn.execute(
                "SELECT part FROM part_confirmations WHERE practice_id=?",
                (pid,))}
            missing = [p for p in db.PARTS if p not in confirmed]
            if missing:
                raise HTTPException(409, {"missing_parts": missing})
            existing = {r["member_id"]: r for r in conn.execute(
                "SELECT * FROM attendance WHERE practice_id=?", (pid,))}
            for m in conn.execute("SELECT id FROM members WHERE active=1"):
                row = existing.get(m["id"])
                if row is None or row["status"] is None:
                    db.upsert_attendance(conn, pid, m["id"],
                                         "absent", None, None, "auto")
            conn.execute(
                "UPDATE practices SET status='closed', closed_at=? WHERE id=?",
                (db.now_kst().isoformat(), pid))
            conn.commit()
        notion = request.app.state.notion
        if notion is not None:
            bg.add_task(notion.sync_close, request.app.state.db_path, pid)
        return {"status": "closed"}

    @app.post("/practices/{pid}/reopen")
    def reopen_practice(pid: int, conn=Depends(get_conn),
                        _=Depends(require_conductor)):
        get_practice(conn, pid)
        conn.execute("UPDATE practices SET status='open' WHERE id=?", (pid,))
        conn.commit()
        return {"status": "open"}
```

- [ ] **Step 4: 통과 확인**

Run: `pytest tests/test_close.py -v --basetemp=.pytest_tmp`
Expected: 7 PASS

- [ ] **Step 5: 커밋**

```bash
git add app/main.py tests/test_close.py
git commit -m "feat: 마감·재오픈 — 4파트 게이트, 자동 결석 확정, 멱등 재마감"
```

---

### Task 9: 본인 통계 — GET /me/stats

**Files:**
- Modify: `app/main.py` (`register_routes` 내부)
- Test: `tests/test_stats.py`

**Interfaces:**
- Consumes: `current_member`, `rules.attendance_rate`
- Produces: `GET /me/stats` → `{"total", "present", "late", "absent", "rate"}` — 마감(closed)된 연습의 본인 행만 집계

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_stats.py`:

```python
from tests.conftest import login
from tests.test_me import make_practice, FUTURE, PAST
from tests.test_close import confirm_all_parts


def closed_practice_with_my_status(client, status_body):
    pid = make_practice(client, FUTURE)
    login(client, "김소", "m1")
    client.put(f"/practices/{pid}/me", json=status_body)
    confirm_all_parts(client, pid)
    assert client.post(f"/practices/{pid}/close").status_code == 200
    return pid


def test_stats_counts_closed_only(client):
    closed_practice_with_my_status(client, {"status": "present"})
    closed_practice_with_my_status(
        client, {"status": "late", "reason": "버스", "eta": "19:30"})
    make_practice(client, PAST)  # open 상태 — 집계 제외
    login(client, "김소", "m1")
    body = client.get("/me/stats").json()
    assert body == {"total": 2, "present": 1, "late": 1, "absent": 0,
                    "rate": 1.0}


def test_stats_auto_absent_counted(client):
    pid = make_practice(client, PAST)   # 아무도 입력 안 함
    confirm_all_parts(client, pid)
    client.post(f"/practices/{pid}/close")
    login(client, "김소", "m1")
    body = client.get("/me/stats").json()
    assert body == {"total": 1, "present": 0, "late": 0, "absent": 1,
                    "rate": 0.0}


def test_stats_empty(client):
    login(client, "김소", "m1")
    assert client.get("/me/stats").json()["total"] == 0
```

- [ ] **Step 2: 실패 확인**

Run: `pytest tests/test_stats.py -v --basetemp=.pytest_tmp`
Expected: FAIL (404)

- [ ] **Step 3: 구현**

`register_routes` 안에 추가:

```python
    @app.get("/me/stats")
    def my_stats(conn=Depends(get_conn), me=Depends(current_member)):
        counts = {"present": 0, "late": 0, "absent": 0}
        rows = conn.execute(
            """SELECT a.status, COUNT(*) AS n FROM attendance a
               JOIN practices p ON p.id = a.practice_id
               WHERE p.status = 'closed' AND a.member_id = ?
               GROUP BY a.status""", (me["id"],))
        for r in rows:
            counts[r["status"]] = r["n"]
        total = sum(counts.values())
        return {"total": total, **counts,
                "rate": rules.attendance_rate(counts["present"],
                                              counts["late"], total)}
```

- [ ] **Step 4: 통과 확인**

Run: `pytest tests/test_stats.py -v --basetemp=.pytest_tmp`
Expected: 3 PASS

- [ ] **Step 5: 커밋**

```bash
git add app/main.py tests/test_stats.py
git commit -m "feat: 본인 출석 통계 — 마감 연습만 집계, 지각=출석 인정"
```

---

### Task 10: notion.py — NotionStore (생성·복원·동기화)

**Files:**
- Create: `app/notion.py`, `tests/fake_notion.py`
- Test: `tests/test_notion.py`

**Interfaces:**
- Consumes: `db.connect`, `db.PARTS`, `db.now_kst`, notion_client.Client 형태의 객체(`databases.create/query/retrieve`, `pages.create/update`, `blocks.children.list`)
- Produces: `notion.NotionStore` —
  - `__init__(self, client, parent_page_id: str)`
  - `ensure_databases(self, conn) -> None` — settings에 `roster_db_id`/`attendance_db_id` 있으면 no-op. 없으면 **먼저 부모 페이지 자식에서 같은 제목("명단"/"출석 기록")의 기존 DB를 재발견**(`blocks.children.list` — child_database 블록의 id가 곧 database id, `databases.retrieve`로 속성 ID 맵 획득)하고, 그래도 없을 때만 생성. id + 속성 ID 맵(JSON)을 settings에 저장. 이 재발견이 없으면 SQLite 유실 후 재부팅 때마다 노션에 새 DB가 중복 생성되고 복원이 빈 DB를 읽는다 — 아키텍처("노션이 영구 원본")의 핵심 계약
  - `refresh_roster(self, conn, state) -> None` — 명단 DB 전체 조회 → members upsert(student_id 기준), 노션에 없는 기존 멤버 `active=0`, 경고는 `state.roster_warnings`에 교체 저장
  - `restore_archive(self, conn, state) -> None` — 출석 기록 DB 전체 조회 → (연습명, 날짜) 기준 practices(closed) 재구성 + attendance 재구성(학번 매칭, notion_page_id 저장)
  - `sync_close(self, db_path: str, practice_id: int) -> None` — **자체 연결 생성**(백그라운드 태스크용). 해당 연습 전체 행 upsert: `notion_page_id` 있으면 `pages.update`, 없으면 `pages.create` 후 id 저장 + **행 단위 즉시 commit**(중간 실패 시 이미 만든 page_id가 보존돼야 재마감 때 중복 생성이 안 됨). 완료 시 `practices.notion_synced_at` 기록. 노션 API 예외는 잡지 않고 전파(마감 자체는 이미 커밋됨, 복구는 재마감)
  - 모듈 상수: `PART_KO = {"soprano": "소프라노", "alto": "알토", "tenor": "테너", "bass": "베이스"}`, `ROLE_KO = {"member": "단원", "part_leader": "파트장", "conductor": "지휘자"}`, `STATUS_KO = {"present": "출석", "late": "지각", "absent": "결석"}` (+ 각 역방향 `KO_PART` 등)
  - `tests/fake_notion.py` 공용 계약: `FakeNotionClient`(내부 dict `fake.dbs`)와 노션 응답 형식 헬퍼 `rich/title/select/checkbox/date` — Task 11 테스트가 `from tests.fake_notion import ...`로 import. 전부 이 파일에 정의

- [ ] **Step 1: FakeClient 작성**

`tests/fake_notion.py` — notion_client.Client의 사용 부분만 흉내내는 dict 기반 대역. 내부 저장은 `fake.dbs`, API 표면은 `fake.databases.*` / `fake.pages.*` / `fake.blocks.children.list(...)`. 노션 응답 형식 헬퍼 5개도 **이 파일에** 정의(테스트 두 파일이 import):

```python
import itertools


class _DBs:
    def __init__(self, fake):
        self.fake = fake

    def create(self, parent, title, properties):
        db_id = f"db{next(self.fake.seq)}"
        props = {name: {"id": f"prop{next(self.fake.seq)}"}
                 for name in properties}
        self.fake.dbs[db_id] = {
            "id": db_id, "parent": parent["page_id"],
            "title": title[0]["text"]["content"],
            "properties": props, "pages": {}}
        return {"id": db_id, "properties": props}

    def retrieve(self, database_id):
        d = self.fake.dbs[database_id]
        return {"id": d["id"], "properties": d["properties"]}

    def query(self, database_id, start_cursor=None, page_size=100):
        pages = list(self.fake.dbs[database_id]["pages"].values())
        return {"results": pages, "has_more": False, "next_cursor": None}


class _Pages:
    def __init__(self, fake):
        self.fake = fake

    def create(self, parent, properties):
        page_id = f"pg{next(self.fake.seq)}"
        page = {"id": page_id, "properties": properties}
        self.fake.dbs[parent["database_id"]]["pages"][page_id] = page
        return page

    def update(self, page_id, properties):
        for database in self.fake.dbs.values():
            if page_id in database["pages"]:
                database["pages"][page_id]["properties"].update(properties)
                return database["pages"][page_id]
        raise KeyError(page_id)


class _Children:
    def __init__(self, fake):
        self.fake = fake

    def list(self, block_id):
        return {"results": [
            {"id": d["id"], "type": "child_database",
             "child_database": {"title": d["title"]}}
            for d in self.fake.dbs.values() if d["parent"] == block_id]}


class _Blocks:
    def __init__(self, fake):
        self.children = _Children(fake)


class FakeNotionClient:
    def __init__(self):
        self.seq = itertools.count(1)
        self.dbs = {}
        self.databases = _DBs(self)
        self.pages = _Pages(self)
        self.blocks = _Blocks(self)


# --- 노션 응답 형식 헬퍼 (테스트에서 페이지 주입용) ---

def rich(text):
    return {"rich_text": [{"plain_text": text, "text": {"content": text}}]}


def title(text):
    return {"title": [{"plain_text": text, "text": {"content": text}}]}


def select(name):
    return {"select": {"name": name}}


def checkbox(v):
    return {"checkbox": v}


def date(iso):
    return {"date": {"start": iso}}
```

참고: FakeClient 페이지의 property 값 dict에는 `"id"` 키가 없으므로 `_by_id`는 이름 폴백 경로로 매칭된다 — 일반 테스트에서 별도 조치 불필요. 컬럼명 변경 내성 테스트만 값 dict에 `"id"`를 직접 넣어 ID 경로를 검증한다.

- [ ] **Step 2: 실패하는 테스트 작성**

`tests/test_notion.py`:

```python
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
```

- [ ] **Step 3: 실패 확인**

Run: `pytest tests/test_notion.py -v --basetemp=.pytest_tmp`
Expected: FAIL (`ModuleNotFoundError: app.notion`)

- [ ] **Step 4: 구현**

`app/notion.py`:

```python
import json

from . import db

PART_KO = {"soprano": "소프라노", "alto": "알토", "tenor": "테너", "bass": "베이스"}
ROLE_KO = {"member": "단원", "part_leader": "파트장", "conductor": "지휘자"}
STATUS_KO = {"present": "출석", "late": "지각", "absent": "결석"}
KO_PART = {v: k for k, v in PART_KO.items()}
KO_ROLE = {v: k for k, v in ROLE_KO.items()}
KO_STATUS = {v: k for k, v in STATUS_KO.items()}

ROSTER_PROPS = {
    "이름": {"title": {}},
    "학번": {"rich_text": {}},
    "파트": {"select": {"options": [{"name": n} for n in PART_KO.values()]}},
    "역할": {"select": {"options": [{"name": n} for n in ROLE_KO.values()]}},
    "활성": {"checkbox": {}},
}
ATTENDANCE_PROPS = {
    "이름": {"title": {}},
    "학번": {"rich_text": {}},
    "파트": {"select": {"options": [{"name": n} for n in PART_KO.values()]}},
    "연습명": {"rich_text": {}},
    "날짜": {"date": {}},
    "상태": {"select": {"options": [{"name": n} for n in STATUS_KO.values()]}},
    "사유": {"rich_text": {}},
}


def _plain(prop):
    """노션 property 값 → 파이썬 값. 이름 변경에 대비해 type으로 분기."""
    if prop is None:
        return None
    if "title" in prop:
        return "".join(t.get("plain_text", "") for t in prop["title"]) or None
    if "rich_text" in prop:
        return "".join(t.get("plain_text", "")
                       for t in prop["rich_text"]) or None
    if "select" in prop:
        return prop["select"]["name"] if prop["select"] else None
    if "checkbox" in prop:
        return prop["checkbox"]
    if "date" in prop:
        return prop["date"]["start"] if prop["date"] else None
    return None


def _by_id(page, prop_ids):
    """페이지 properties를 {필드명: 값}으로. 저장된 속성 ID 우선, 이름 폴백."""
    values = {}
    props = page["properties"]
    id_to_prop = {p.get("id"): p for p in props.values() if isinstance(p, dict)}
    for field, pid in prop_ids.items():
        prop = id_to_prop.get(pid)
        if prop is None:
            prop = props.get(field)
        values[field] = _plain(prop)
    return values


def _rich(text):
    return {"rich_text": [{"text": {"content": text or ""}}]}


class NotionStore:
    def __init__(self, client, parent_page_id):
        self.client = client
        self.parent_page_id = parent_page_id

    # ---------- settings ----------
    @staticmethod
    def _get(conn, key):
        row = conn.execute("SELECT value FROM settings WHERE key=?",
                           (key,)).fetchone()
        return row["value"] if row else None

    @staticmethod
    def _set(conn, key, value):
        conn.execute("INSERT INTO settings (key, value) VALUES (?, ?) "
                     "ON CONFLICT (key) DO UPDATE SET value=excluded.value",
                     (key, value))

    # ---------- bootstrap ----------
    def ensure_databases(self, conn):
        """settings에 id가 있으면 no-op. 없으면 부모 페이지에서 기존 DB를
        재발견(SQLite 유실 후 재부팅 시나리오)하고, 그래도 없으면 생성.
        재발견 없이는 재배포마다 노션에 새 DB가 중복 생성된다."""
        if self._get(conn, "roster_db_id") and self._get(conn, "attendance_db_id"):
            return
        existing = {}  # 제목 → database_id (child_database 블록 id == db id)
        children = self.client.blocks.children.list(
            block_id=self.parent_page_id)
        for block in children["results"]:
            if block.get("type") == "child_database":
                existing[block["child_database"]["title"]] = block["id"]
        for key, name, props in (
                ("roster", "명단", ROSTER_PROPS),
                ("attendance", "출석 기록", ATTENDANCE_PROPS)):
            if name in existing:
                meta = self.client.databases.retrieve(
                    database_id=existing[name])
            else:
                meta = self.client.databases.create(
                    parent={"type": "page_id", "page_id": self.parent_page_id},
                    title=[{"text": {"content": name}}],
                    properties=props)
            self._set(conn, f"{key}_db_id", meta["id"])
            self._set(conn, f"{key}_prop_ids", json.dumps(
                {n: p["id"] for n, p in meta["properties"].items()}))
        conn.commit()

    def _prop_ids(self, conn, key):
        return json.loads(self._get(conn, f"{key}_prop_ids") or "{}")

    def _query_all(self, database_id):
        pages, cursor = [], None
        while True:
            kwargs = {"database_id": database_id, "page_size": 100}
            if cursor:
                kwargs["start_cursor"] = cursor
            resp = self.client.databases.query(**kwargs)
            pages.extend(resp["results"])
            if not resp.get("has_more"):
                return pages
            cursor = resp.get("next_cursor")

    # ---------- roster ----------
    def refresh_roster(self, conn, state):
        prop_ids = self._prop_ids(conn, "roster")
        warnings, seen = [], set()
        for page in self._query_all(self._get(conn, "roster_db_id")):
            v = _by_id(page, prop_ids)
            part = KO_PART.get(v.get("파트") or "")
            role = KO_ROLE.get(v.get("역할") or "") or "member"
            name, sid = v.get("이름"), v.get("학번")
            if not name or not sid or part is None:
                warnings.append(
                    f"명단 행 무시: 이름={name!r} 학번={sid!r} 파트={v.get('파트')!r}")
                continue
            # 체크박스 미설정(None)은 활성으로 취급, 명시적 False만 비활성
            active = 0 if v.get("활성") is False else 1
            seen.add(sid)
            conn.execute(
                """INSERT INTO members
                     (name, student_id, part, role, active, notion_page_id)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT (student_id) DO UPDATE SET
                     name=excluded.name, part=excluded.part, role=excluded.role,
                     active=excluded.active,
                     notion_page_id=excluded.notion_page_id""",
                (name, sid, part, role, active, page["id"]))
        if seen:
            placeholders = ",".join("?" for _ in seen)
            conn.execute(
                f"UPDATE members SET active=0 WHERE student_id NOT IN "
                f"({placeholders})", tuple(seen))
        conn.commit()
        state.roster_warnings[:] = warnings

    # ---------- archive restore ----------
    def restore_archive(self, conn, state):
        prop_ids = self._prop_ids(conn, "attendance")
        members = {r["student_id"]: r["id"]
                   for r in conn.execute("SELECT id, student_id FROM members")}
        practice_ids = {}
        warnings = []
        for page in self._query_all(self._get(conn, "attendance_db_id")):
            v = _by_id(page, prop_ids)
            sid, title_, start = v.get("학번"), v.get("연습명"), v.get("날짜")
            status = KO_STATUS.get(v.get("상태") or "")
            if not sid or not title_ or not start or status is None:
                warnings.append(f"기록 행 무시: 학번={sid!r} 연습명={title_!r}")
                continue
            member_id = members.get(sid)
            if member_id is None:
                warnings.append(f"기록 행 무시: 명단에 없는 학번 {sid!r}")
                continue
            pkey = (title_, start)
            if pkey not in practice_ids:
                cur = conn.execute(
                    """INSERT INTO practices
                         (title, starts_at, status, closed_at, notion_synced_at)
                       VALUES (?, ?, 'closed', ?, ?)""",
                    (title_, start, start, db.now_kst().isoformat()))
                practice_ids[pkey] = cur.lastrowid
            conn.execute(
                """INSERT INTO attendance
                     (practice_id, member_id, status, reason, eta, source,
                      updated_at, notion_page_id)
                   VALUES (?, ?, ?, ?, NULL, 'auto', ?, ?)""",
                (practice_ids[pkey], member_id, status, v.get("사유"),
                 db.now_kst().isoformat(), page["id"]))
        conn.commit()
        state.roster_warnings.extend(warnings)

    # ---------- close sync ----------
    def sync_close(self, db_path, practice_id):
        conn = db.connect(db_path)
        try:
            self.ensure_databases(conn)
            att_db = self._get(conn, "attendance_db_id")
            practice = conn.execute("SELECT * FROM practices WHERE id=?",
                                    (practice_id,)).fetchone()
            rows = conn.execute(
                """SELECT a.id, a.status, a.reason, a.notion_page_id,
                          m.name, m.student_id, m.part
                   FROM attendance a JOIN members m ON m.id = a.member_id
                   WHERE a.practice_id=?""", (practice_id,)).fetchall()
            for r in rows:
                props = {
                    "이름": {"title": [{"text": {"content": r["name"]}}]},
                    "학번": _rich(r["student_id"]),
                    "파트": {"select": {"name": PART_KO[r["part"]]}},
                    "연습명": _rich(practice["title"]),
                    "날짜": {"date": {"start": practice["starts_at"]}},
                    "상태": {"select": {"name": STATUS_KO[r["status"]]}},
                    "사유": _rich(r["reason"]),
                }
                if r["notion_page_id"]:
                    self.client.pages.update(page_id=r["notion_page_id"],
                                             properties=props)
                else:
                    page = self.client.pages.create(
                        parent={"database_id": att_db}, properties=props)
                    conn.execute(
                        "UPDATE attendance SET notion_page_id=? WHERE id=?",
                        (page["id"], r["id"]))
                    # 행 단위 커밋 — 중간 실패 시에도 이미 만든 page_id를
                    # 보존해야 재마감 때 같은 단원의 페이지가 중복 생성 안 됨
                    conn.commit()
            conn.execute(
                "UPDATE practices SET notion_synced_at=? WHERE id=?",
                (db.now_kst().isoformat(), practice_id))
            conn.commit()
        finally:
            conn.close()
```

- [ ] **Step 5: 통과 확인**

Run: `pytest tests/test_notion.py -v --basetemp=.pytest_tmp`
Expected: 9 PASS

- [ ] **Step 6: 커밋**

```bash
git add app/notion.py tests/fake_notion.py tests/test_notion.py
git commit -m "feat: 노션 스토어 — DB 자동 생성, 명단 갱신, 기록 복원, 마감 동기화"
```

---

### Task 11: 부팅 복원 + 백그라운드 동기화 연결 + README

**Files:**
- Modify: `app/main.py` (lifespan, `__main__` 블록)
- Create: `README.md`
- Test: `tests/test_restore.py`

**Interfaces:**
- Consumes: `NotionStore.ensure_databases/refresh_roster/restore_archive/sync_close`
- Produces:
  - `create_app(db_path, notion=None)` — notion이 있으면 시작 시(lifespan) `ensure_databases` → members 테이블이 비어 있으면 `refresh_roster` + `restore_archive` 실행
  - `__main__` 실행 시 `config.NOTION_TOKEN` 있으면 `notion_client.Client`로 NotionStore 구성해 주입
  - close 후 FakeNotion에 페이지 생김(백그라운드 태스크 실행 검증 — TestClient는 응답 후 즉시 실행)

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_restore.py`:

```python
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
            "SELECT notion_page_id FROM attendance a JOIN members m "
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
```

- [ ] **Step 2: 실패 확인**

Run: `pytest tests/test_restore.py -v --basetemp=.pytest_tmp`
Expected: FAIL (복원 로직 없음 — 로그인 401)

- [ ] **Step 3: 구현**

`app/main.py`의 `create_app`을 lifespan 포함으로 수정 (모듈 상단 `from contextlib import asynccontextmanager`):

```python
def create_app(db_path: str, notion=None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if app.state.notion is not None:
            conn = app.state.conn
            app.state.notion.ensure_databases(conn)
            empty = conn.execute(
                "SELECT COUNT(*) FROM members").fetchone()[0] == 0
            if empty:
                app.state.notion.refresh_roster(conn, app.state)
                app.state.notion.restore_archive(conn, app.state)
        yield

    app = FastAPI(lifespan=lifespan)
    # ... 기존 state 설정·라우트 등록 그대로 ...
```

`__main__` 블록 교체:

```python
if __name__ == "__main__":
    import os

    import uvicorn

    notion = None
    if config.NOTION_TOKEN and config.NOTION_PARENT_PAGE_ID:
        from notion_client import Client

        from .notion import NotionStore
        notion = NotionStore(Client(auth=config.NOTION_TOKEN),
                             config.NOTION_PARENT_PAGE_ID)
    uvicorn.run(create_app(config.DB_PATH, notion=notion),
                host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
```

`README.md`:

```markdown
# 합창단 출석 관리 백엔드

50명 이하 합창단의 연습 출석을 관리하는 FastAPI 앱. 노션이 영구 원본,
SQLite는 휘발 작업장. 설계: docs/superpowers/specs/2026-07-24-attendance-backend-design.md

## 실행

    pip install -r requirements.txt
    set NOTION_TOKEN=secret_xxx
    set NOTION_PARENT_PAGE_ID=xxxx
    set SECRET_KEY=random-string
    python -m app.main

노션 준비: 빈 페이지 하나 만들고 integration을 연결하면 앱이 첫 실행 때
명단·출석 기록 DB를 자동 생성한다. 명단 관리는 노션에서 직접.

## 배포 (Render 무료)

- Build: `pip install -r requirements.txt`
- Start: `python -m app.main` (PORT 환경변수 자동 인식)
- 환경변수: NOTION_TOKEN, NOTION_PARENT_PAGE_ID, SECRET_KEY
- **슬립 방지**: cron-job.org에서 10분 간격 `GET /health` 등록 (무료 750h/월로 상시 가동)
- 연습 당일 배포 금지 — 마감 전 사전 입력은 SQLite에만 있어 재시작 시 유실

## 테스트

    pytest --basetemp=.pytest_tmp
```

- [ ] **Step 4: 통과 확인**

Run: `pytest tests/ -v --basetemp=.pytest_tmp`
Expected: 전체 스위트 PASS

- [ ] **Step 5: 커밋**

```bash
git add app/main.py README.md tests/test_restore.py
git commit -m "feat: 부팅 시 노션 복원, 마감 백그라운드 동기화 연결, README"
```

---

## 계획 밖 (스펙의 범위 외 항목 재확인)

프런트엔드, 정기 일정 자동 생성, 푸시 알림, WebSocket/SSE, PIN 인증, 수정자 추적, 실제 도착 시각. Render 배포 실행과 cron-job.org 등록은 코드 밖 운영 작업 — README 지침으로 대체.
