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
            try:
                start = db.to_kst_naive_iso(start)
            except ValueError:
                warnings.append(f"기록 행 무시: 잘못된 날짜 형식 {start!r}")
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
