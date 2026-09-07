"""GLEE 운영 앱 진입점. 노션이 원본이며 모든 API는 operations_routes 에 있다.

SQLite(DB_PATH)는 노션 데이터베이스·보기 ID 캐시일 뿐이다. 재배포로 사라져도 부모 페이지에서 재발견한다.
노션이 설정되지 않으면 운영 API는 503으로 거부한다 — SQLite만으로 성공 응답하지 않는다(설계).
"""
import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles

from . import config, db
from .operations_routes import install


def create_app(db_path: str, notion=None) -> FastAPI:
    app = FastAPI()
    app.state.db_path = db_path
    app.state.conn = db.connect(db_path)
    app.state.notion = notion
    install(app, notion, app.state.conn)

    @app.get("/health")
    def health():
        return {"ok": True, "storage": "notion", "configured": notion is not None}

    @app.middleware("http")
    async def revalidate_frontend(request: Request, call_next):
        # JS/CSS/HTML은 배포 후 낡은 캐시가 남지 않도록 항상 재검증 (ETag → 304)
        response = await call_next(request)
        if request.url.path == "/" or request.url.path.endswith((".js", ".css", ".html")):
            response.headers["Cache-Control"] = "no-cache"
        return response

    app.mount("/", StaticFiles(directory=Path(__file__).parent / "static", html=True), name="static")
    return app


if __name__ == "__main__":
    import os

    import uvicorn

    notion = None
    if config.NOTION_TOKEN and config.NOTION_PARENT_PAGE_ID:
        from notion_client import Client

        from .notion import NotionStore
        notion = NotionStore(Client(auth=config.NOTION_TOKEN), config.NOTION_PARENT_PAGE_ID)
    if notion is None:
        logging.getLogger("attendance").warning(
            "NOTION 미설정 — 운영 API는 저장을 거부합니다. 노션 연결을 설정하세요.")
    if config.SECRET_KEY == "dev-secret":
        logging.getLogger("attendance").warning(
            "SECRET_KEY가 기본값(dev-secret) — 프로덕션에서 반드시 설정하세요.")
    # Render 같은 TLS 종료 프록시 뒤에서는 X-Forwarded-Proto/Host 를 신뢰해야
    # CSRF 출처 검사(request.base_url)와 세션 쿠키 Secure 판정(url.scheme)이 맞는다.
    uvicorn.run(create_app(config.DB_PATH, notion=notion), host="0.0.0.0",
                port=int(os.environ.get("PORT", 8000)), proxy_headers=True, forwarded_allow_ips="*")
