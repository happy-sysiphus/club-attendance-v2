import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Request, Response
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


class StatusIn(BaseModel):
    status: str
    reason: str | None = None
    eta: str | None = None


class PartIn(BaseModel):
    part: str


def effective_row(att, practice) -> dict:
    starts_at = datetime.fromisoformat(practice["starts_at"])
    raw = (att["status"], att["source"]) if att else (None, None)
    status, source = rules.effective_status(raw[0], raw[1], starts_at, db.now_kst())
    return {"status": status, "source": source,
            "reason": att["reason"] if att else None,
            "eta": att["eta"] if att else None}


def register_routes(app: FastAPI) -> None:
    """Task 4~9에서 라우트를 이 함수 안에 추가한다."""

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
        if not body.title.strip():
            raise HTTPException(422, "title 필수")
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

    @app.post("/practices/{pid}/reopen")
    def reopen_practice(pid: int, conn=Depends(get_conn),
                        _=Depends(require_conductor)):
        get_practice(conn, pid)
        conn.execute("UPDATE practices SET status='open' WHERE id=?", (pid,))
        conn.commit()
        return {"status": "open"}


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
