# 합창단 출석 관리

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

- **출석 탭**: 기존 출석 입력·현황판·연습 관리.
- **일정 탭**: 월간 달력, 이전·다음 달과 오늘 이동, 날짜별 연습 시간·장소.
  단원은 출석 입력으로, 파트장·지휘자는 현황판으로 이동할 수 있다.
  지휘자는 달력에서 선택한 날짜로 새 연습을 등록하고 기존 연습을 수정·삭제한다.
- 별도 프런트엔드 라이브러리나 빌드 과정은 없다.

## 파트와 출석 대상

명단의 파트: 소프라노 / 알토 / 테너 / 베이스 / 반주자 / 지휘자.

- 지휘자는 출석 입력·집계·자동 결석·파트 확인 대상에서 제외된다.
  본인 출석률 대신 전체 현황판을 사용한다.
- 반주자는 일반 단원과 같은 출석 입력·통계 규칙을 적용한다.
  반주자 파트의 수정·확인은 지휘자가 맡으며 별도 파트장 권한을 부여하지 않는다.
- 기존 성부 4개는 기존처럼 확인이 필요하다. 반주자는 **활성 반주자가 있을 때만**
  마감 전 확인이 필요하며, 지휘자 확인 항목은 없다.

업데이트 후 첫 실행에서 기존 SQLite 명단 테이블의 파트 제약을 확장하고
기존 지휘자의 파트를 전환한다. 단원 ID와 과거 출석 기록은 보존한다.
노션 연동 시 기존 명단·출석 DB의 선택지를 보존하면서 반주자·지휘자를 추가한다.
노션 명단에서 지휘자 파트 또는 지휘자 역할은 지휘자로, 반주자 파트는 단원 역할로
읽어 들인다. 명단은 서버 시작 시와 로그인 명단 불일치 시 갱신한다.

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
