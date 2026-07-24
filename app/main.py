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
