"""Human-readable Notion properties for the operations app (2022 database API)."""

ADMIN = {"단장": "head", "홍보": "publicity", "총무": "treasurer"}
KINDS = {"rehearsal": "연습", "regular": "정기공연", "external": "외부공연", "admin": "행정"}
# field: (Notion property name, type, optional relation target)
SCHEMAS = {
    "semesters": ("학기 관리", {
        "title": ("학기", "title"), "key": ("앱 키", "rich_text"),
        "year": ("연도", "number"), "half": ("학기 번호", "number"),
        "starts_at": ("시작", "date"), "ends_at": ("종료", "date"),
        "state": ("운영 상태", "select"), "previous": ("이전 학기", "rich_text"),
        "carry": ("확정 이월금", "number"), "carry_at": ("이월 확정 시각", "date"),
        "carry_by": ("이월 확정자", "rich_text"),
        "transition_at": ("학기 전환 기준", "date"),
    }),
    "songs": ("전체 곡 목록", {
        "title": ("곡명", "title"), "key": ("앱 키", "rich_text"),
        "composer": ("작곡가", "rich_text"), "arranger": ("편곡자", "rich_text"),
        "created_by": ("등록자", "rich_text"),
    }),
    "events": ("전체 일정", {
        "title": ("일정", "title"), "key": ("앱 키", "rich_text"),
        "category": ("분류", "select"), "kind": ("일정 유형", "select"),
        "starts_at": ("시작", "date"), "ends_at": ("종료", "date"),
        "all_day": ("종일", "checkbox"), "place": ("장소", "rich_text"),
        "description": ("설명", "rich_text"), "status": ("상태", "select"),
        "semester": ("학기", "relation", "semesters"),
        "songs": ("공연 곡", "relation", "songs"), "song_order": ("곡 순서", "rich_text"),
        "photos": ("사진", "files"), "photo_meta": ("사진 업로드 기록", "rich_text"),
        "confirmations": ("파트 확인", "rich_text"),
        "created_by": ("등록자", "rich_text"), "closed_at": ("출석 마감 시각", "date"),
    }),
    "materials": ("곡별 자료", {
        "title": ("자료명", "title"), "key": ("앱 키", "rich_text"),
        "song": ("곡", "relation", "songs"), "kind": ("자료 유형", "select"),
        "required": ("확인 필수", "checkbox"), "files": ("파일", "files"),
        "rehearsal_date": ("연습 날짜", "date"), "uploaded_at": ("등록 시각", "date"),
        "created_by": ("등록자", "rich_text"),
    }),
    "acknowledgements": ("자료 확인 기록", {
        "title": ("확인 기록", "title"), "key": ("앱 키", "rich_text"),
        "material": ("자료", "relation", "materials"),
        "semester": ("학기", "relation", "semesters"),
        "member": ("단원 ID", "rich_text"), "member_name": ("확인자", "rich_text"),
        "opened_at": ("열람 시각", "date"), "confirmed_at": ("확인 시각", "date"),
    }),
    "attendance": ("출석 기록", {
        "title": ("이름", "title"), "key": ("앱 키", "rich_text"),
        "event": ("일정", "relation", "events"), "semester": ("학기", "relation", "semesters"),
        # 기존 출석 기록 DB에 이미 있는 열. 노션에서 직접 볼 때 신규 행도 같은 열이 채워지도록 함께 기록한다.
        "practice_title": ("연습명", "rich_text"), "date": ("날짜", "date"),
        "member": ("단원 ID", "rich_text"), "student_id": ("학번", "rich_text"),
        "part": ("파트", "select"), "status": ("상태", "select"),
        "reason": ("사유", "rich_text"), "eta": ("도착 예정", "rich_text"),
        "source": ("입력 역할", "select"), "updated_at": ("수정 시각", "date"),
    }),
}

LEDGER = {
    "title": ("내용", "title"), "date": ("날짜", "date"),
    "direction": ("구분", "select"), "classification": ("분류", "select"),
    "amount": ("금액", "number"), "owner": ("담당자", "rich_text"),
    "note": ("비고", "rich_text"), "semester": ("학기", "relation", "semesters"),
    "key": ("앱 키", "rich_text"),
}
