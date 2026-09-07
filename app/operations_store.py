"""Notion is the source of truth; SQLite only caches discovered database IDs.

Writes are synchronous. Stable operation keys recover creates after a lost response.
Run a single application worker: the lock serializes compound Notion operations.
"""
import copy
import json
import logging
import math
import os
import time
from threading import RLock

import httpx
from notion_client.errors import APIResponseError, HTTPResponseError, RequestTimeoutError

from . import config, db
from .notion import KO_PART, KO_ROLE
from .operations_schema import ADMIN, LEDGER, SCHEMAS

log = logging.getLogger("attendance")
# 노션 조회 결과를 이 시간 동안 재사용한다. 앱의 쓰기는 캐시를 직접 갱신하므로 앱 안의 변경은 즉시 반영되고,
# 노션에서 직접 고친 내용만 최대 이 시간 뒤에 보인다. 새로고침(fresh=1)은 캐시를 건너뛴다.
CACHE_SECONDS = float(os.environ.get("NOTION_CACHE_SECONDS", "60"))
# 재시도로 해결되지 않는 노션 오류 — 속성 이름·형식·권한 문제라 원인을 그대로 사용자에게 알린다.
PERMANENT_CODES = {"validation_error", "object_not_found", "unauthorized", "restricted_resource", "invalid_request"}
# 데이터베이스 위치를 환경변수 ID로 고정한다. 지정된 DB는 어느 페이지에 있어도 되고(통합 연결만 필요),
# 재배포로 SQLite 캐시가 사라져도 제목 탐색·중복 생성 없이 그 ID를 쓴다. 미지정이면 부모 페이지에서 찾거나 만든다.
ENV_IDS = {kind: f"NOTION_{kind.upper()}_DATABASE_ID" for kind in (*SCHEMAS, "roster", "ledger")}


class NotionUnavailable(Exception):
    pass


def text_value(prop):
    return "".join(x.get("plain_text", x.get("text", {}).get("content", ""))
                   for x in prop.get(prop.get("type", "rich_text"), []))


class OperationsStore:
    def __init__(self, notion, conn):
        self.notion, self.client, self.conn = notion, notion.client, conn
        self.ids, self.props, self.ready = {}, {}, False
        self.lock = RLock()
        self.last_call = 0.0
        self.ledger_categories = []
        self.roster_warnings = []   # 명단에서 건너뛴 행 — 현황판에서 지휘자에게 노출
        self._cache = {}            # kind -> (rows, monotonic 시각). 'roster'도 같은 형식

    def call(self, fn, **kwargs):
        # 노션 SDK 오류만 NotionUnavailable로 바꾼다. 코드 버그(TypeError 등)는 그대로 올려 500과 스택으로 드러나게 둔다.
        for attempt in range(4):
            time.sleep(max(0, .35 - (time.monotonic() - self.last_call)))
            self.last_call = time.monotonic()
            try:
                return fn(**kwargs)
            except (APIResponseError, HTTPResponseError, RequestTimeoutError) as exc:
                status = getattr(exc, "status", None)
                code = str(getattr(exc, "code", "") or "")
                transient = status in (429, 502, 503, 504) or isinstance(exc, RequestTimeoutError)
                if transient and attempt < 3:
                    time.sleep(1 + attempt)
                    continue
                log.exception("Notion call failed: %s status=%s code=%s", getattr(fn, "__name__", fn), status, code)
                if code in PERMANENT_CODES:
                    raise NotionUnavailable(f"노션이 요청을 거부했습니다({code}). 재시도로 해결되지 않습니다 — "
                                            f"노션 속성 이름·형식·통합 권한을 확인해 주세요: {exc}") from exc
                raise NotionUnavailable("노션 요청에 실패했습니다. 입력을 유지한 채 다시 시도해 주세요.") from exc

    def all_pages(self, database_id):
        pages, cursor = [], None
        while True:
            args = {"database_id": database_id, "page_size": 100}
            if cursor:
                args["start_cursor"] = cursor
            result = self.call(self.client.databases.query, **args)
            pages.extend(result["results"])
            if not result.get("has_more"):
                return pages
            cursor = result["next_cursor"]

    def _retrieve(self, kind, label, database_id):
        """DB 메타를 읽는다. 실패하면 어떤 DB·어떤 설정이 문제인지 그대로 말한다."""
        try:
            return self.call(self.client.databases.retrieve, database_id=database_id)
        except NotionUnavailable as exc:
            source = f"환경변수 {ENV_IDS[kind]}" if os.environ.get(ENV_IDS[kind]) else "저장된 ID"
            raise NotionUnavailable(
                f"'{label}' 데이터베이스({database_id})에 접근할 수 없습니다 — {source} 값이 맞는지, "
                f"노션에서 그 DB(또는 상위 페이지)의 연결(Connections)에 통합이 추가돼 있는지 확인해 주세요.") from exc

    def bootstrap(self):
        if self.ready:
            return
        env = {kind: os.environ.get(name, "").strip() for kind, name in ENV_IDS.items()}
        # 명단·출석 기록은 기존 노션 계층이 관리한다. 환경변수 ID가 있으면 그 계층이 탐색 때 저장하는
        # 것과 같은 settings(DB ID + 속성 ID 맵)를 먼저 채워, ensure_databases가 탐색·생성을 건너뛰고
        # 파트 선택지만 보강하게 한다. 속성 ID 맵이 없으면 _ensure_part_options가 '파트'를 못 찾아 실패한다.
        for kind, label in (("roster", "명단"), ("attendance", "출석 기록")):
            if env[kind]:
                meta = self._retrieve(kind, label, env[kind])
                self.notion._set(self.conn, f"{kind}_db_id", meta["id"])
                self.notion._set(self.conn, f"{kind}_prop_ids",
                                 json.dumps({n: p["id"] for n, p in meta["properties"].items()}))
        self.conn.commit()
        try:
            self.notion.ensure_databases(self.conn)
        except Exception as exc:
            raise NotionUnavailable(f"노션 명단·출석 데이터베이스 연결을 확인해 주세요: {exc}") from exc
        existing = {}
        # 부모 페이지 스캔은 환경변수·캐시 어느 쪽에도 ID가 없는 DB가 있을 때만 (첫 설치 또는 미지정 재배포)
        if any(not env[k] and not self.notion._get(self.conn, f"ops_{k}_id") for k in SCHEMAS if k != "attendance"):
            cursor = None
            while True:
                args = {"block_id": self.notion.parent_page_id, "page_size": 100}
                if cursor:
                    args["start_cursor"] = cursor
                result = self.call(self.client.blocks.children.list, **args)
                for block in result["results"]:
                    if block["type"] == "child_database":
                        existing[block["child_database"]["title"]] = block["id"]
                if not result.get("has_more"):
                    break
                cursor = result["next_cursor"]
        for kind, (name, fields) in SCHEMAS.items():
            database_id = env[kind] or self.notion._get(self.conn, f"ops_{kind}_id") or existing.get(name)
            if kind == "attendance":
                database_id = env[kind] or self.notion._get(self.conn, "attendance_db_id")
            definitions = {}
            for field, (label, typ, *target) in fields.items():
                definitions[label] = {typ: ({"database_id": self.ids[target[0]],
                                           "single_property": {}} if typ == "relation" else {})}
            if database_id:
                meta = self._retrieve(kind, name, database_id)
                missing = {k: v for k, v in definitions.items() if k not in meta["properties"]}
                if missing:
                    meta = self.call(self.client.databases.update, database_id=database_id, properties=missing)
            else:
                meta = self.call(self.client.databases.create,
                                 parent={"page_id": self.notion.parent_page_id},
                                 title=[{"text": {"content": name}}], properties=definitions)
            self.ids[kind] = meta["id"]
            self.props[kind] = {field: meta["properties"][value[0]]["id"] for field, value in fields.items()}
            self.notion._set(self.conn, f"ops_{kind}_id", meta["id"])
            self.conn.commit()
        roster_id = env["roster"] or self.notion._get(self.conn, "roster_db_id")
        roster = self._retrieve("roster", "명단", roster_id)
        admin_prop = roster["properties"].get("행정 직군")
        if admin_prop is None:
            self.call(self.client.databases.update, database_id=roster_id,
                      properties={"행정 직군": {"select": {"options": [{"name": n} for n in ADMIN]}}})
        elif admin_prop.get("type") != "select":
            # 형식이 다르면 admin_role이 조용히 전부 빈 값이 돼 단장·총무 권한이 사라진다 → 명시적으로 실패
            raise NotionUnavailable("노션 명단의 '행정 직군' 속성은 선택(select) 형식이어야 합니다.")
        self.ids["roster"] = roster_id
        # 실제 회계장부를 그대로 쓴다(스펙 §8). 개발·테스트 때는 NOTION_LEDGER_DATABASE_ID 로 사본을 지정할 것.
        ledger_id = env["ledger"] or "4379fa3860c94a498dbae5e444dd9afd"
        ledger = self._retrieve("ledger", "회계장부", ledger_id)
        additions = {}
        for field in ("semester", "key"):
            label, typ, *target = LEDGER[field]
            if label not in ledger["properties"]:
                additions[label] = {typ: {"database_id": self.ids["semesters"], "single_property": {}} if target else {}}
        if additions:
            ledger = self.call(self.client.databases.update, database_id=ledger_id, properties=additions)
        # 기존 장부 속성은 이름·형식을 가정한다. 어긋나면 KeyError 500이 아니라 원인이 보이는 설정 오류로 실패한다.
        for field, (label, typ, *_) in LEDGER.items():
            prop = ledger["properties"].get(label)
            if prop is None:
                raise NotionUnavailable(f"회계장부에 '{label}' 속성이 없습니다. 노션 장부의 열 이름을 확인해 주세요.")
            if prop.get("type") != typ:
                raise NotionUnavailable(f"회계장부의 '{label}' 속성은 {typ} 형식이어야 합니다(현재 {prop.get('type')}).")
        self.ids["ledger"] = ledger_id
        self.props["ledger"] = {field: ledger["properties"][value[0]]["id"] for field, value in LEDGER.items()}
        self.ledger_categories = [o["name"] for o in ledger["properties"]["분류"]["select"]["options"]]
        self.ready = True

    def cached(self, name, fresh, load):
        hit = self._cache.get(name)
        if not fresh and hit and time.monotonic() - hit[1] < CACHE_SECONDS:
            return copy.deepcopy(hit[0])   # load()가 행을 제자리에서 고치므로(unpack 등) 복사본을 준다
        rows = load()
        self._cache[name] = (copy.deepcopy(rows), time.monotonic())
        return rows

    def read(self, kind, fresh=False):
        return self.cached(kind, fresh, lambda: [self._row(kind, page) for page in self.all_pages(self.ids[kind])])

    def _row(self, kind, page):
        """노션 페이지 객체 → 앱 행. save()가 돌려받은 페이지에도 그대로 써서 캐시를 갱신한다."""
        fields = LEDGER if kind == "ledger" else SCHEMAS[kind][1]
        by_id = {p["id"]: p for p in page["properties"].values()}
        row = {"id": page["id"], "edited_at": page["last_edited_time"]}
        for field, (label, typ, *_) in fields.items():
            p = by_id.get(self.props[kind][field], page["properties"].get(label, {}))
            value = p.get(typ)
            if typ in ("title", "rich_text"):
                value = text_value(p)
            elif typ == "relation":
                values = list(value or [])
                if p.get("has_more"):
                    values, cursor = [], None
                    while True:
                        args = {"page_id": page["id"], "property_id": p["id"], "page_size": 100}
                        if cursor:
                            args["start_cursor"] = cursor
                        relations = self.call(self.client.pages.properties.retrieve, **args)
                        values.extend(x["relation"] for x in relations["results"])
                        if not relations.get("has_more"):
                            break
                        cursor = relations["next_cursor"]
                value = [x["id"] for x in values]
                if field != "songs":
                    value = value[0] if value else ""
            elif typ == "date":
                value = value["start"] if value else ""
                if value and "T" in value:
                    try:
                        value = db.to_kst_naive_iso(value)
                    except ValueError:
                        value = ""   # 노션에서 직접 넣은 이상한 날짜는 빈 값으로 (notion.py와 동일한 관대함)
            elif typ == "select":
                value = value["name"] if value else ""
            elif typ == "files":
                value = value or []
            row[field] = value
        return row

    def roster(self, fresh=False):
        return self.cached("roster", fresh, self._roster)

    def _roster(self):
        result, warnings = [], []
        pages = self.all_pages(self.ids["roster"])
        for page in pages:
            p = page["properties"]
            val = lambda k: text_value(p.get(k, {}))
            sel = lambda k: (p.get(k, {}).get("select") or {}).get("name", "")
            part, role = KO_PART.get(sel("파트")), KO_ROLE.get(sel("역할"), "member")
            if part == "conductor" or role == "conductor":
                part, role = "conductor", "conductor"
            if not part or not val("이름") or not val("학번"):
                # 파트 오타·이름/학번 누락 행. 조용히 빼면 그 단원이 출석 대상에서 사라지고 아무도 모른다 → 경고로 노출
                warnings.append(f"명단 행 무시: 이름={val('이름') or '(없음)'} 학번={val('학번') or '(없음)'} 파트={sel('파트') or '(없음)'}")
                continue
            result.append({"id": page["id"], "member_id": page["id"], "name": val("이름"),
                           "student_id": val("학번"), "part": part,
                           "role": "member" if part == "accompanist" else role,
                           "admin_role": ADMIN.get(sel("행정 직군"), ""),
                           "active": p.get("활성", {}).get("checkbox", True)})
        if pages and not result:
            # 전 행이 걸러졌다면 열 이름·형식이 바뀐 것이다. '빈 명단'(=전원 로그아웃)으로 위장하지 않는다.
            raise NotionUnavailable("노션 명단을 한 명도 읽지 못했습니다. '이름'·'학번'·'파트'·'역할' 열 이름과 형식을 확인해 주세요.")
        # Invalid duplicate exclusive roles fail closed instead of granting two editors.
        for role in ("head", "treasurer"):
            if sum(m["active"] and m["admin_role"] == role for m in result) > 1:
                raise NotionUnavailable(f"노션 명단에서 {'단장' if role == 'head' else '총무'}는 활성 단원 1명만 지정해 주세요.")
        self.roster_warnings = warnings
        return result

    def save(self, kind, data, page_id=None):
        fields = LEDGER if kind == "ledger" else SCHEMAS[kind][1]
        props = {}
        for field, value in data.items():
            if field not in fields:
                continue
            label, typ, *_ = fields[field]
            if typ in ("title", "rich_text"):
                value = str(value or "")
                value = [{"text": {"content": value[i:i+1800]}} for i in range(0, len(value), 1800)]
            elif typ == "select":
                value = {"name": value} if value else None
            elif typ == "date":
                value = {"start": value + "+09:00" if "T" in value and "+" not in value and not value.endswith("Z") else value} if value else None
            elif typ == "relation":
                value = [{"id": x} for x in (value if isinstance(value, list) else [value]) if x]
            props[self.props[kind][field]] = {typ: value}
        if page_id:
            page = self.call(self.client.pages.update, page_id=page_id, properties=props)
        else:
            # Query the operation key immediately before creating, also after restarts.
            key = data.get("key")
            if key:
                found = self.call(self.client.databases.query, database_id=self.ids[kind],
                                  filter={"property": self.props[kind]["key"], "rich_text": {"equals": key}})
                if found["results"]:
                    return found["results"][0]["id"]
            page = self.call(self.client.pages.create, parent={"database_id": self.ids[kind]}, properties=props)
        self._patch(kind, page)
        return page["id"]

    def _patch(self, kind, page):
        # 쓰기 응답으로 캐시를 직접 갱신한다 — 다음 요청이 전량 재조회하지 않는다.
        hit = self._cache.get(kind)
        if hit:
            rows = [r for r in hit[0] if r["id"] != page["id"]]
            rows.append(self._row(kind, page))
            self._cache[kind] = (rows, hit[1])

    def delete(self, page_id):
        # Notion's API delete is archive; no extra application deletion history.
        self.call(self.client.pages.update, page_id=page_id, archived=True)
        for name, (rows, at) in list(self._cache.items()):
            if any(r["id"] == page_id for r in rows):
                self._cache[name] = ([r for r in rows if r["id"] != page_id], at)

    def modern(self, method, path, **kwargs):
        """Only view management uses 2026 API; existing database SDK stays pinned."""
        headers = {"Authorization": f"Bearer {config.NOTION_TOKEN}",
                   "Notion-Version": "2026-03-11"}
        for attempt in range(4):
            time.sleep(max(0, .35 - (time.monotonic() - self.last_call)))
            self.last_call = time.monotonic()
            try:
                response = httpx.request(method, "https://api.notion.com/v1/" + path,
                                         headers=headers, timeout=30, **kwargs)
                if response.status_code == 429 and attempt < 3:
                    time.sleep(1 + attempt)
                    continue
                response.raise_for_status()
                return response.json()
            except httpx.HTTPError as exc:
                raise NotionUnavailable("노션 학기별 보기 연결을 완료하지 못했습니다. 다시 시도해 주세요.") from exc

    def ensure_semester_views(self, semester):
        for kind in ("events", "attendance", "ledger", "acknowledgements"):
            setting = f"ops_view:{kind}:{semester['id']}"
            if self.notion._get(self.conn, setting):
                continue
            database_id = self.ids[kind]
            database = self.modern("GET", f"databases/{database_id}")
            sources = database.get("data_sources", [])
            if len(sources) != 1:
                raise NotionUnavailable("학기별 보기를 만들 데이터 소스는 데이터베이스당 하나여야 합니다.")
            found, cursor = None, None
            while True:
                args = {"database_id": database_id, "page_size": 100}
                if cursor:
                    args["start_cursor"] = cursor
                views = self.modern("GET", "views", params=args)
                for ref in views["results"]:
                    view = ref if "name" in ref else self.modern("GET", f"views/{ref['id']}")
                    if view.get("name") == semester["title"]:
                        found = view
                        break
                if found or not views.get("has_more"):
                    break
                cursor = views["next_cursor"]
            if not found:
                found = self.modern("POST", "views", json={
                    "database_id": database_id, "data_source_id": sources[0]["id"],
                    "name": semester["title"], "type": "table",
                    "filter": {"property": self.props[kind]["semester"], "relation": {"contains": semester["id"]}},
                })
            self.notion._set(self.conn, setting, found["id"])
            self.conn.commit()

    def upload(self, file, filename, content_type, size):
        headers = {"Authorization": f"Bearer {config.NOTION_TOKEN}", "Notion-Version": "2022-06-28"}
        chunk_size = 10 * 1024 * 1024
        multi = size > 20 * 1024 * 1024
        payload = {"filename": filename, "content_type": content_type,
                   "mode": "multi_part" if multi else "single_part"}
        if multi:
            payload["number_of_parts"] = math.ceil(size / chunk_size)
        try:
            with httpx.Client(headers=headers, timeout=120) as client:
                r = client.post("https://api.notion.com/v1/file_uploads", json=payload)
                r.raise_for_status()
                upload_id = r.json()["id"]
                count = payload.get("number_of_parts", 1)
                for index in range(count):
                    chunk = file.read(chunk_size if multi else size)
                    r = client.post(f"https://api.notion.com/v1/file_uploads/{upload_id}/send",
                                    files={"file": (filename, chunk, content_type)},
                                    data={"part_number": str(index + 1)} if multi else {})
                    r.raise_for_status()
                    if not multi and r.json().get("status") != "uploaded":
                        raise NotionUnavailable("파일 업로드가 완료되지 않았습니다.")
                if multi:
                    r = client.post(f"https://api.notion.com/v1/file_uploads/{upload_id}/complete")
                    r.raise_for_status()
                    if r.json().get("status") != "uploaded":
                        raise NotionUnavailable("파일 업로드가 완료되지 않았습니다.")
            return {"name": filename, "type": "file_upload", "file_upload": {"id": upload_id}}
        except httpx.HTTPError as exc:
            raise NotionUnavailable("파일 저장에 실패했습니다. 노션 파일 용량 제한과 연결을 확인하고 다시 시도해 주세요.") from exc
