import sqlite3
from datetime import datetime

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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(create_app(config.DB_PATH), host="0.0.0.0", port=8000)
