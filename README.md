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

## 화면

`python -m app.main` 후 `http://localhost:8000/` 접속. 프런트는 `app/static/`의
순수 HTML+JS(빌드 없음)이며 같은 서버가 서빙한다. 설계:
docs/superpowers/specs/2026-08-23-frontend-design.md

로컬 확인용 명단 시드(노션 없이):

    python -c "from tests.conftest import SEED; from app import db; c=db.connect('attendance.db'); c.executemany('INSERT OR IGNORE INTO members (name, student_id, part, role) VALUES (?,?,?,?)', SEED); c.commit()"

## 배포 (Render 무료)

- Build: `pip install -r requirements.txt`
- Start: `python -m app.main` (PORT 환경변수 자동 인식)
- 환경변수: NOTION_TOKEN, NOTION_PARENT_PAGE_ID, SECRET_KEY
- **슬립 방지**: cron-job.org에서 10분 간격 `GET /health` 등록 (무료 750h/월로 상시 가동)
- 연습 당일 배포 금지 — 마감 전 사전 입력은 SQLite에만 있어 재시작 시 유실

## 테스트

    pytest --basetemp=.pytest_tmp
