# GLEE 출석·일정·운영 관리

FastAPI와 빌드 없는 HTML/JavaScript로 구성한 글리 운영 앱입니다. 노션이 기준 저장소이며, 저장 성공은 노션 쓰기가 끝난 뒤에만 반환합니다.

## 실행

PowerShell 예시:

```powershell
pip install -r requirements.txt
$env:NOTION_TOKEN = '<integration token>'
$env:NOTION_PARENT_PAGE_ID = '<운영 부모 페이지 ID>'
$env:NOTION_LEDGER_DATABASE_ID = '4379fa3860c94a498dbae5e444dd9afd'
# 나머지 7개 DB도 ID로 고정 (아래 "노션 데이터베이스 ID 고정" 표) — 지정하면 위치와 무관, 미지정이면 부모 페이지에서 탐색·생성
$env:NOTION_ROSTER_DATABASE_ID = '3c5749fe4c67814b9858cbb2d7778028'
$env:NOTION_ATTENDANCE_DATABASE_ID = '3c5749fe4c678147bdc6fa4361f871a1'
$env:NOTION_SEMESTERS_DATABASE_ID = '3d4749fe4c6781f0bfd5fd69c60aead9'
$env:NOTION_EVENTS_DATABASE_ID = '3d4749fe4c678173b30ccc32ceb84074'
$env:NOTION_SONGS_DATABASE_ID = '3d4749fe4c678118980fdace30a0e35f'
$env:NOTION_MATERIALS_DATABASE_ID = '3d4749fe4c6781a4b8d7ff28632f10cc'
$env:NOTION_ACKNOWLEDGEMENTS_DATABASE_ID = '3d4749fe4c67819abd7fddabb8de28e4'
$env:SECRET_KEY = '<충분히 긴 임의의 문자열>'
python -m app.main
```

`http://localhost:8000/`에 접속합니다. 노션 integration에 부모 페이지와 **기존 회계장부**를 모두 연결해야 합니다. `NOTION_LEDGER_DATABASE_ID`를 생략하면 제공받은 26-2 GLEE 장부를 사용합니다. 노션 연결 없이 임시 SQLite 저장으로 운영하지 않습니다.

첫 인증 요청에서 명단·출석 기록을 재사용하고 전체 일정·학기 관리·전체 곡 목록·곡별 자료·자료 확인 기록 DB 및 필요한 속성을 준비합니다. 기존 회계장부를 새로 만들지 않으며 기존 수식과 분류를 유지합니다. 첫 학기는 2026년 2학기입니다.

## 노션 데이터베이스 ID 고정

앱이 쓰는 노션 DB 8개는 모두 환경변수로 ID를 지정할 수 있습니다. **지정된 DB는 노션 어디에 있어도 됩니다** — 해당 DB(또는 상위 페이지)에 integration이 연결돼 있기만 하면 됩니다. 지정하지 않은 DB는 재배포마다 `NOTION_PARENT_PAGE_ID` 페이지의 **직속 자식에서 제목으로** 다시 찾고, 없으면 새로 만듭니다. Render는 재배포 때 SQLite 캐시가 사라지므로 **전부 지정하는 것을 권장**합니다 — 그래야 DB를 옮기거나 제목을 바꿔도 빈 DB가 중복 생성되지 않습니다.

| 환경변수 | 노션 DB | 현재 값 (2026-09-07) |
| --- | --- | --- |
| `NOTION_ROSTER_DATABASE_ID` | 명단 (`지휘부 / 출석`) | `3c5749fe4c67814b9858cbb2d7778028` |
| `NOTION_ATTENDANCE_DATABASE_ID` | 출석 기록 (`지휘부 / 출석`) | `3c5749fe4c678147bdc6fa4361f871a1` |
| `NOTION_SEMESTERS_DATABASE_ID` | 학기 관리 (`지휘부 / 출석`) | `3d4749fe4c6781f0bfd5fd69c60aead9` |
| `NOTION_EVENTS_DATABASE_ID` | 전체 일정 (`지휘부 / 출석`) | `3d4749fe4c678173b30ccc32ceb84074` |
| `NOTION_SONGS_DATABASE_ID` | 전체 곡 목록 (`지휘부 / 출석`) | `3d4749fe4c678118980fdace30a0e35f` |
| `NOTION_MATERIALS_DATABASE_ID` | 곡별 자료 (`지휘부 / 출석`) | `3d4749fe4c6781a4b8d7ff28632f10cc` |
| `NOTION_ACKNOWLEDGEMENTS_DATABASE_ID` | 자료 확인 기록 (`지휘부 / 출석`) | `3d4749fe4c67819abd7fddabb8de28e4` |
| `NOTION_LEDGER_DATABASE_ID` | 26-2 GLEE 회계 장부 (`재정 (총무)`) | `4379fa3860c94a498dbae5e444dd9afd` (기본값) |

ID는 노션에서 DB를 열었을 때 URL의 `/p/<32자리>` 부분입니다(대시 유무 무관). 접근이 안 되면 앱이 어떤 DB·어떤 변수가 문제인지 오류 문구로 알려줍니다. 회계장부는 `출석`과 다른 페이지 트리에 있으므로 integration을 **따로 연결**해야 합니다(장부 또는 `재정 (총무)` 페이지의 연결에 추가).

## 화면과 권한

- 출석: 지휘·행정 구분 없이 오늘부터의 전체 일정을 가까운 날짜순으로 표시합니다. 연습·공연에서 기존 출석 규칙을 사용합니다.
- 일정: 월간 캘린더, 지난 일정, 공연 날짜 강조, 날짜 목록·일정 상세와 사진을 제공합니다.
- 지휘: 지휘자·파트장·반주자만 접근합니다. 공연별 곡, 전체 곡 라이브러리, 필기본·음원, 학기별 확인 기록을 관리합니다. 자료 편집은 지휘자만 가능합니다.
- 행정: 단장·홍보가 모든 일정 사진을 관리합니다. 기한이 지난 사진 미등록 일정에 느낌표와 탭 배지를 표시합니다. 행정 일정 등록·수정은 단장만 가능합니다.
- 재정: 모두 조회하고 총무만 편집합니다. 학기별 수입·지출·이월금·잔액과 분류별 지출을 표시합니다.
- 학기: 단장이 마감하면 다음 학기가 자동 생성됩니다. 시작 전 일정은 자동 이동하고 과거 기록은 계속 조회·수정할 수 있습니다.

명단은 노션에서 관리합니다. 음악 파트/역할과 행정 직군은 별개입니다. 행정 직군은 단장·홍보·총무 중 1개이며 단장/총무는 각각 활성 1명, 홍보는 여러 명을 허용합니다. 지휘자는 출석 대상에서 제외하고 반주자는 일반 단원과 동일하게 출석을 기록합니다. 반주자 파트 확인은 지휘자가 담당합니다.

## 저장과 파일

노션에 일정, 출석, 사진, 곡, 파일, 확인 시각, 학기, 회계를 저장합니다. SQLite는 DB/보기 ID 캐시입니다. 페이지를 열면 노션에서 새로 불러옵니다. 조회 실패 시 마지막 내용에 최신 정보가 아님을 표시하고 편집을 막습니다.

사진 JPG/PNG/HEIC, 필기본 PDF/이미지, 음원 MP3/M4A/WAV를 업로드합니다. 기본 서버 제한은 파일당 200MB이며 `MAX_UPLOAD_MB`로 조정할 수 있습니다. 노션 workspace 요금제의 파일 제한도 적용됩니다. HEIC 인라인 표시는 브라우저에 따라 다를 수 있어 원본 열기 링크를 제공합니다.

## 배포 설정

- Build: `pip install -r requirements.txt`
- Start: `python -m app.main`
- 환경변수: `NOTION_TOKEN`, `NOTION_PARENT_PAGE_ID`, `SECRET_KEY`, 그리고 "노션 데이터베이스 ID 고정" 표의 `NOTION_*_DATABASE_ID` 8개(권장). 선택적으로 `DB_PATH`, `MAX_UPLOAD_MB`, `NOTION_CACHE_SECONDS`(기본 60초), `PORT`
- 단일 프로세스/worker로 실행합니다. 복수 Notion 페이지 갱신은 프로세스 내 잠금으로 직렬화합니다.
- `/health`는 프로세스와 설정 상태를 반환합니다. 노션 연결 테스트를 수행하는 endpoint는 아닙니다.
- 학기별 Notion 보기는 2026-03-11 Views API로 준비합니다. 기존 데이터베이스 SDK는 기존 버전을 유지합니다.
- 기존 정수 회원 ID 쿠키로는 재로그인이 필요합니다.

## 구현 및 다음 작업

기획: [합의된 요구사항](docs/2026-09-07-agreed-product-spec.md)

구현 직후의 검증 계획은 [리뷰·검증 인수인계](docs/implementation-review-handoff.md)에, 그 뒤 수행한 코드 리뷰·수정·격리 환경 실측(학기별 보기 API, 사진 업로드·삭제·교체, 분할 업로드) 결과는 [운영 확장 리뷰](docs/2026-09-07-operations-review.md)에 있습니다. 옛 SQLite 경로 테스트는 삭제했고 신규 코드의 자동 테스트는 아직 없습니다(인수인계 문서의 fake `OperationsStore` 권고 참고).