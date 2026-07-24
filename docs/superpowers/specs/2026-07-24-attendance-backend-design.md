# 합창단 출석 관리 — 백엔드 설계 스펙

작성일: 2026-07-24
상태: 확정 (구현 전)

## 1. 목적

50명 이하 대학 합창단의 정기 연습 출석 관리. 설문형 출석체크가 아니라, 연습 시작
직후 지휘자가 실시간으로 확인하는 운영 도구다.

- 아직 오지 않은 단원 / 지각 예정 단원(사유·예상 도착 시간) / 결석 단원
- 파트별 출석 확인 진행 상황

이 문서는 백엔드와 출석 처리 규칙의 설계를 확정한다. 프런트엔드는 후순위.

## 2. 역할과 조직

파트: 소프라노 / 알토 / 테너 / 베이스

| 역할 | 인원 | 권한 요약 |
|---|---|---|
| 단원 | ≤50 | 본인 예정 상태 입력(시작 시각까지), 본인 상태·통계 조회 |
| 파트장 | 파트당 1명 | 자기 파트 조회·수정(마감까지), 자기 파트 확인 완료 |
| 지휘자 | 1명 | 전체 조회·수정, 연습 CRUD, 마감·재오픈, 임의 파트 확인 대행 |

단원은 다른 사람의 출석 상태를 볼 수 없다.

## 3. 아키텍처

- **FastAPI 단일 서버** (Python). 프런트는 추후 같은 서버가 정적 파일로 서빙.
- **실시간 = 5초 폴링.** WebSocket/SSE 없음. 현황판 GET을 프런트가 주기 호출.
  동시 조회자는 지휘자 1 + 파트장 4 수준이라 부하 무의미. 폴링 엔드포인트는
  첫 로드·재동기화에도 그대로 쓰이므로 추후 SSE를 얹더라도 버려지지 않는다.
- **자동 결석 = 지연 평가.** 스케줄러·크론 없음. 조회 시점에
  `now >= starts_at`이고 상태가 미확정이면 결석(auto)으로 계산해 반환.
  DB 기록은 마감 시점에 한 번만 확정(materialize).
- **시간대 = KST 고정.** 저장·비교·표시 전부 `Asia/Seoul` 나이브 시각.
  `now()`는 KST를 반환하는 헬퍼 하나로 통일. UTC 변환 계층 없음.

## 4. 저장 구조 — 노션이 원본, SQLite는 작업장

### 4.1 역할 분담

| 저장소 | 역할 | 유실 시 |
|---|---|---|
| 노션 (Plus 플랜) | **영구 원본.** 명단 DB + 출석 기록 DB(마감분) | 없음 (원본) |
| SQLite 파일 | **휘발 작업장.** 연습 진행 중 실시간 조작 전담 | 노션에서 재구성 |

- 연습 진행 중 조작(사전 입력, 파트장 수정, 현황판)은 절대 노션 API를 타지
  않는다. 노션은 속도(요청당 300ms~1s), 초당 ~3요청 제한, 쓰기 직후 쿼리
  미반영(일관성), 유니크 제약 부재 때문에 실시간 백엔드로 부적합.
- 부팅 시 노션에서 명단·과거 마감 기록을 SQLite로 복원한다
  (한 학기 ~30연습 × 50명 = 1,500행 ≈ 요청 15회, 페이지네이션 루프).
- 마감되지 않은 진행 중 데이터는 SQLite에만 존재한다. 서버 크래시·배포로
  디스크가 초기화되면 그 시점의 사전 입력은 유실된다 — 감수하기로 결정.
  파트장 확인 단계가 전수 검증이므로 피해는 "미리 적은 사유가 사라짐" 수준.

### 4.2 명단 관리 = 노션에서 직접

앱에 명단 CRUD API·관리 화면이 없다. 지휘자가 노션 명단 DB에서 행을 직접
추가·수정한다. 노션이 곧 관리자 UI다.

- 탈단: 노션에서 행 삭제가 아니라 **활성 체크 해제**. 삭제하면 복원 시 과거
  기록과 명단 매칭이 끊긴다. 비활성 단원은 로그인 불가, 이후 연습의
  명단·자동결석·현황판에서 제외, 과거 마감 기록은 보존.
- 앱은 명단을 SQLite에 캐시하고 부팅 시 + 주기적(또는 로그인 실패 시)으로 갱신.

### 4.3 노션 스키마 — 앱이 자동 생성

지휘자 수작업은 두 가지뿐: ① 노션에 빈 페이지 생성 ② integration 연결.
앱이 첫 실행 시 그 페이지 아래 DB 두 개를 만들고 `database_id`를 저장한다.

`database_id` 매핑은 SQLite(settings)에 있으므로 서버 재배포로 SQLite가
초기화되면 사라진다. 따라서 부팅 시 settings에 id가 없으면 **부모 페이지의
자식에서 같은 제목의 기존 DB를 먼저 재발견해 재사용**하고, 없을 때만
생성한다. 이 재발견이 없으면 재배포마다 노션에 빈 DB가 중복 생성되고
복원이 실패한다 — "노션이 영구 원본" 전제의 필수 조건.

```text
📋 명단 DB
  이름(title) | 학번(rich_text) | 파트(select: 소프라노/알토/테너/베이스)
  | 역할(select: 단원/파트장/지휘자) | 활성(checkbox, 기본 켬)

✅ 출석 기록 DB (행 = 연습 × 단원)
  이름(title) | 학번 | 파트 | 연습명 | 날짜(date)
  | 상태(select: 출석/지각/결석) | 사유(rich_text)
  ※ 예상 도착 시간(eta)은 동기화하지 않음 — 운영용 정보이지 최종 기록이 아님
```

- 읽기는 **속성 ID 기준**. 생성 시 속성 ID를 저장해 두고 ID로 접근하므로
  지휘자가 컬럼명을 바꿔도 깨지지 않는다.
- 파싱은 관대하게: 잘못된 행(파트 오타 등)은 건너뛰고 검증 에러를 로그 +
  현황판 응답에 노출해 지휘자가 알 수 있게 한다.

## 5. SQLite 데이터 모델

```text
members                      # 노션 명단 캐시
  id            PK
  name          text
  student_id    text UNIQUE
  part          soprano | alto | tenor | bass
  role          member | part_leader | conductor
  active        bool
  notion_page_id text        # 명단 행 매칭 키

practices
  id            PK
  title         text
  starts_at     datetime (KST)
  place         text
  status        open | closed
  closed_at     datetime null
  notion_synced_at datetime null   # 마지막 동기화 완료 시각

attendance
  id            PK
  practice_id   FK
  member_id     FK
  status        present | late | absent | null   # null = 미확정
  reason        text null
  eta           text null          # "HH:MM" 텍스트, 사람이 읽는 값
  source        member | part_leader | conductor | auto
  updated_at    datetime
  notion_page_id text null         # 출석 기록 행 upsert 키
  UNIQUE(practice_id, member_id)

part_confirmations
  practice_id   FK
  part          text
  confirmed_at  datetime
  UNIQUE(practice_id, part)

settings                     # key-value: 노션 database_id, 속성 ID 맵 등
  key           text PK
  value         text
```

설계 결정:

- 예정 상태와 확정 상태를 컬럼으로 분리하지 않는다. 행 하나에 `source`로
  마지막 입력 주체만 구분. 이력 테이블 없음.
- 수정자(누가 바꿨나) 추적 컬럼 없음 — 결정 사항. `source`가 역할 수준까지만 기록.
- attendance 행은 입력 발생 시 생성(지연 생성). 현황판은 members와 outer join.
- 세션 테이블 없음. 로그인 성공 시 member_id를 담은 서명 토큰을 쿠키로 발급,
  서버는 서명만 검증.

## 6. 출석 상태와 규칙

상태: `출석(present)` / `지각(late)` / `결석(absent)` / 미확정(null)

| 상태 | 필수 입력 | 선택 입력 |
|---|---|---|
| 출석 | — | — (부가 정보 무시) |
| 지각 | 사유, 예상 도착 시간(HH:MM) | — |
| 결석 | — | 사유 |

- 검증 규칙은 함수 하나로 공유 (본인 입력 PUT과 관리자 수정 PUT 동일 적용).
- 지각자가 실제 도착해도 상태는 `지각` 유지 — 그것이 최종 기록.
  도착 확인 액션·도착 시각 기록 없음. 안 온 지각자는 마감 전에 파트장·지휘자가
  `결석`으로 변경한다.

### 시간 창

```text
연습 생성 ───────── starts_at ───────────── 마감(close)
단원 본인 입력:    가능        ✕ (잠김)
파트장/지휘자:     가능        가능
화면 표시:        입력값       null이면 "결석(auto)"
DB 확정:                                    close 시 null → absent(source=auto)
```

## 7. API — 13 엔드포인트

```text
인증
  POST   /auth/login                {name, student_id} → 명단 매칭 → 서명 쿠키
                                    로그아웃은 클라이언트 쿠키 삭제

연습 (쓰기는 지휘자만)
  POST   /practices                 생성 {title, starts_at, place}
  GET    /practices                 목록 — 전 역할
  PUT    /practices/{id}            수정 — open일 때만
  DELETE /practices/{id}            삭제 — open일 때만 (마감분은 삭제 불가)
  POST   /practices/{id}/close      마감 (아래 8절)
  POST   /practices/{id}/reopen     재오픈 — status=open (지휘자만)

본인 입력 (단원)
  GET    /practices/{id}/me         내 상태
  PUT    /practices/{id}/me         예정 상태 입력 — starts_at 전 + open일 때만

현황판 (5초 폴링 대상)
  GET    /practices/{id}/board      파트장 → 자기 파트만
                                    지휘자 → 4파트 전체 + 파트별 확인 여부
                                             + 노션 동기화 상태 + 명단 파싱 경고
                                    단원   → 403
                                    auto-absent 계산 반영된 상태로 반환

상태 수정
  PUT    /practices/{id}/members/{member_id}
                                    파트장 → 자기 파트 단원만 / 지휘자 → 전체
                                    open일 때만
  POST   /practices/{id}/part/confirm   {part}
                                    파트장 → 자기 파트만 / 지휘자 → 임의 파트 대행

통계
  GET    /me/stats                  본인 통계 (마감된 연습만 집계)
                                    → {총 연습, 출석, 지각, 결석, 출석률}
```

권한 위반은 403, 마감된 연습 수정 시도는 409, 검증 실패는 422.

## 8. 마감 · 재오픈 · 노션 동기화

### close (지휘자만)

1. **4파트 모두 확인 완료가 아니면 409 거부.** 파트장 부재 시 지휘자가
   `/part/confirm`으로 대행 후 마감.
2. 미확정(null) 전원을 `absent, source=auto`로 확정.
3. `status=closed`, `closed_at` 기록. 응답은 즉시 반환.
4. 노션 동기화는 백그라운드 태스크로 실행 (50명 ≈ 17초, 초당 ~3요청 제한).
   완료 시 `notion_synced_at` 기록 — 현황판 폴링으로 지휘자가 확인.

### 동기화 (upsert)

- 각 attendance 행: `notion_page_id` 있으면 노션 페이지 update, 없으면
  create 후 page_id 저장. 재마감해도 같은 페이지 갱신 — 중복 행 원천 불가능.
- 동기화 실패해도 마감은 유효. **close는 멱등**: 이미 closed인 연습에 다시
  호출하면 동기화만 재실행. 실패 복구 = 마감 버튼 다시 누르기.

### reopen (지휘자만)

- `status=open`으로 되돌림. **part_confirmations는 유지** — 재오픈은 소수
  정정 용도이지 재검표가 아니므로, 수정 후 즉시 재마감 가능.
- 재마감 시 기존 노션 페이지를 update.

## 9. 출석률

- 출석률 = (출석 + 지각) / 전체. **지각은 출석으로 인정.**
- 마감된 연습만 집계 (진행 중 데이터는 미확정이므로 제외).
- 백엔드는 횟수 + 율만 반환. 표시 방식은 프런트 몫.

## 10. 인증

- 이름 + 학번 → 명단(캐시) 매칭 → member_id를 담은 서명 토큰을 쿠키 발급.
- PIN·비밀번호 없음 (지휘자·파트장 포함) — 동아리 내부 신뢰 기반, 편의 우선.
  사칭 위험은 인지하고 수용. 수정자 추적도 하지 않기로 결정.

## 11. 운영

- 호스팅: Render 무료 티어.
- 유휴 슬립 방지: cron-job.org(또는 UptimeRobot)이 10분마다 헬스체크 GET.
  Render 무료 750시간/월 ≥ 한 달 최대 744시간이므로 상시 가동 가능.
- 배포·크래시 직후에는 진행 중 사전 입력이 유실될 수 있음 — 연습 당일 배포 금지.
- 환경 변수: `NOTION_TOKEN`, `NOTION_PARENT_PAGE_ID`, 토큰 서명 키.

## 12. 테스트 전략

pytest (`--basetemp=.pytest_tmp`), FastAPI TestClient + 임시 SQLite 파일,
노션 클라이언트는 mock.

집중 대상 — 규칙이 코드의 전부인 앱이므로 규칙 매트릭스가 곧 테스트:

1. 권한 매트릭스: 역할 3 × 엔드포인트 (파트장 타파트 수정 403, 단원 board 403 등)
2. 검증 규칙: 지각에 사유/eta 누락 → 422, 시작 후 단원 셀프 입력 → 403
3. 지연 평가: 시작 전 null → 미확정, 시작 후 null → 결석(auto) 표시, DB는 null 유지
4. 마감: 4파트 미확인 409, null → absent 확정, 재마감 멱등,
   재오픈 후 수정 → 재마감 시 노션 update(create 아님)
5. 출석률: (출석+지각)/전체, 마감된 연습만 집계
6. 복원: 노션 mock 데이터에서 명단·과거 기록 재구성, 잘못된 행 스킵 + 경고,
   SQLite 유실 후 재부팅 시 기존 노션 DB 재발견(중복 생성 없음)

## 13. 범위 외 (이번 구현에서 하지 않음)

- 프런트엔드 상세 설계 (파트장 화면은 "확인 필요 우선형" B안 선호만 기록)
- 정기 일정 자동 생성, 학기 일정 일괄 등록
- 푸시 알림 (대시보드 내 갱신으로 대체)
- WebSocket/SSE (필요 시 폴링 위에 추가)
- PIN 등 추가 인증, 수정자 추적
- 실제 도착 시각 기록
