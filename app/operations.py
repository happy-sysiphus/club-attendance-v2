"""Role-aware operations service. All successful writes have reached Notion."""
import copy
import json
from datetime import datetime
from uuid import UUID

from fastapi import HTTPException

from . import db, rules
from .notion import PART_KO, STATUS_KO, KO_STATUS
from .operations_schema import KINDS
from .operations_store import NotionUnavailable


def now():
    return db.now_kst().isoformat()


def packed(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def unpack(value, default):
    try:
        return json.loads(value) if value else default
    except (ValueError, TypeError):
        return default


def find(rows, row_id, message="항목이 없습니다"):
    row = next((r for r in rows if r["id"] == row_id), None)
    if row is None:
        raise HTTPException(404, message)
    return row


def text(body, key, required=False, limit=2000):
    value = body.get(key, "")
    if value is None and not required:
        return ""
    if not isinstance(value, str) or len(value) > limit or (required and not value.strip()):
        raise HTTPException(422, f"{key}: 올바른 값을 입력해 주세요 (최대 {limit}자)")
    return value.strip()


def operation_key(body):
    value = text(body, "request_id", True, 36)
    try:
        return str(UUID(value))
    except ValueError:
        raise HTTPException(422, "request_id는 UUID 형식이어야 합니다")


def is_music(me):
    return me["role"] in ("conductor", "part_leader") or me["part"] == "accompanist"


def is_recipient(me):
    return me["role"] != "conductor" and (me["role"] == "part_leader" or me["part"] == "accompanist")


def can_photo(me):
    return me["admin_role"] in ("head", "publicity")


def require(allowed, message="권한이 없습니다"):
    if not allowed:
        raise HTTPException(403, message)


def performance(event):
    return event["kind"] in ("정기공연", "외부공연")


def cancelled(event):
    return event["status"] in ("cancelled", "cancelling", "deleting")


def missing_photo(event):
    return not cancelled(event) and not event["photos"] and (event["ends_at"] or event["starts_at"])[:10] < now()[:10]


def next_semester(year, half):
    # 2026년 2학기 → 2027년 1학기 → 2027년 2학기 … (프런트는 이 값을 받아 쓰고 따로 계산하지 않는다)
    return (year + 1, 1) if half == 2 else (year, 2)


def next_semester_title(semester):
    year, half = next_semester(int(semester["year"]), int(semester["half"]))
    return f"{year}년 {half}학기"


class Operations:
    def __init__(self, store):
        self.store = store
        self.cache = {}

    def load(self, fresh=False):
        s = self.store
        s.bootstrap()
        data = {kind: s.read(kind, fresh) for kind in ("semesters", "songs", "events", "materials", "acknowledgements", "attendance", "ledger")}
        data["members"] = s.roster(fresh)
        # Notion permits unfinished blank rows. They are drafts, not app events.
        data["events"] = [e for e in data["events"] if e["title"] and e["starts_at"] and e["semester"] and e["category"] in ("지휘", "행정")]
        data["songs"] = [song for song in data["songs"] if song["title"]]
        data["materials"] = [m for m in data["materials"] if m["song"] and m["files"]]
        ledger_total = len(data["ledger"])
        data["ledger"] = [r for r in data["ledger"] if r["title"] and r["direction"] in ("수입", "지출")]
        # 제목 없거나 구분이 수입/지출이 아닌 장부 행은 앱 잔액에서 빠진다. 노션 수식 잔액과 어긋날 수 있으니 개수를 노출한다.
        data["ledger_ignored"] = ledger_total - len(data["ledger"])
        # 학기 관리 DB의 빈 초안 행(year/half 없음)은 정렬·int() 에서 TypeError → /api/state 500. 다른 kind와 같이 걸러낸다.
        data["semesters"] = [s for s in data["semesters"] if s["title"] and s["year"] is not None and s["half"] is not None]
        if not data["semesters"]:
            s.save("semesters", {"key": "semester:2026:2", "title": "2026년 2학기", "year": 2026,
                                  "half": 2, "state": "active", "starts_at": now()})
            data["semesters"] = s.read("semesters")
        initial = self.current(data)
        # First adoption assigns the existing ledger to 2026-2. Later unassigned
        # entries created directly in Notion belong to the currently active term.
        for row in data["ledger"]:
            if not row["semester"]:
                row["semester"] = initial["id"]
                s.save("ledger", {"semester": initial["id"]}, row["id"])
        for semester in data["semesters"]:
            if semester["state"] != "pending":
                s.ensure_semester_views(semester)
        for event in data["events"]:
            event["status"] = event["status"] or "open"
            event["song_order"] = unpack(event["song_order"], [])
            event["songs"] = [i for i in event["song_order"] if i in event["songs"]] + [i for i in event["songs"] if i not in event["song_order"]]
            event["confirmations"] = unpack(event["confirmations"], {})
            event["photo_meta"] = unpack(event["photo_meta"], {})
        return data

    def member(self, data, member_id):
        me = next((m for m in data["members"] if m["id"] == member_id and m["active"]), None)
        if not me:
            for key in list(self.cache):
                if key[0] == member_id:
                    self.cache.pop(key, None)
            raise HTTPException(401, "로그인 필요")
        return me

    def current(self, data):
        active = [s for s in data["semesters"] if s["state"] == "active"]
        if not active:
            raise NotionUnavailable("학기 전환이 진행 중입니다. 마감하기를 다시 실행해 주세요.")
        return max(active, key=lambda s: (s["year"], s["half"]))

    def selected(self, data, semester):
        return find(data["semesters"], semester) if semester else self.current(data)

    def wanted_materials(self, data, semester):
        songs = {sid for e in data["events"] if e["semester"] == semester and performance(e) and not cancelled(e) for sid in e["songs"]}
        latest = {}
        for m in sorted(data["materials"], key=lambda m: (m["uploaded_at"], m["id"])):
            if m["kind"] == "score":
                latest[m["song"]] = m["id"]
        return [m for m in data["materials"] if m["song"] in songs and m["required"]
                and (m["kind"] != "score" or latest.get(m["song"]) == m["id"])]

    def finance(self, data, semester):
        rows = [r for r in data["ledger"] if r["semester"] == semester["id"]]
        income = sum(r["amount"] or 0 for r in rows if r["direction"] == "수입")
        expense = sum(r["amount"] or 0 for r in rows if r["direction"] == "지출")
        carry = semester["carry"] or 0
        previous = next((s for s in data["semesters"] if s["id"] == semester["previous"]), None)
        suggested = 0
        if previous:
            suggested = (previous["carry"] or 0) + sum((r["amount"] or 0) * (1 if r["direction"] == "수입" else -1)
                        for r in data["ledger"] if r["semester"] == previous["id"])
        categories = {}
        for r in rows:
            if r["direction"] == "지출":
                categories[r["classification"]] = categories.get(r["classification"], 0) + (r["amount"] or 0)
        return {"rows": sorted(rows, key=lambda r: (r["date"], r["id"]), reverse=True), "income": income,
                "expense": expense, "carry": carry, "balance": carry + income - expense,
                "carry_suggested": suggested, "carry_needs_confirmation": bool(previous) and (not semester["carry_at"] or carry != suggested),
                "categories": categories, "classifications": self.store.ledger_categories,
                "ignored_rows": data.get("ledger_ignored", 0),
                "all_time_net": sum((r["amount"] or 0) * (1 if r["direction"] == "수입" else -1) for r in data["ledger"])}

    def snapshot(self, member_id, semester=None, fresh=False):
        with self.store.lock:
            try:
                data = self.load(fresh)
                me = self.member(data, member_id)
                selected = self.selected(data, semester)
                sid = selected["id"]
                events = [e for e in data["events"] if e["semester"] == sid and e["status"] != "deleting"]
                required = self.wanted_materials(data, sid)
                confirmed = {a["material"] for a in data["acknowledgements"] if a["member"] == me["id"] and a["semester"] == sid and a["confirmed_at"]}
                missing = [m["id"] for m in required if m["id"] not in confirmed] if is_recipient(me) else []
                stats = {"present": 0, "late": 0, "absent": 0}
                closed = {e["id"] for e in events if e["status"] == "closed" and e["category"] == "지휘"}
                for a in data["attendance"]:
                    status = KO_STATUS.get(a["status"])
                    if a["event"] in closed and a["member"] == me["id"] and status:
                        stats[status] += 1
                stats["total"] = sum(stats.values())
                stats["rate"] = rules.attendance_rate(stats["present"], stats["late"], stats["total"])
                recipients = [m for m in data["members"] if m["active"] and is_recipient(m)]
                acks = [a for a in data["acknowledgements"] if a["semester"] == sid and (me["role"] == "conductor" or a["member"] == me["id"])] if is_music(me) else []
                result = {"me": {k: v for k, v in me.items() if k != "student_id"}, "semester": selected,
                          "semesters": sorted(data["semesters"], key=lambda s: (s["year"], s["half"]), reverse=True),
                          "current_semester": self.current(data)["id"],
                          "next_semester_title": next_semester_title(self.current(data)), "events": events,
                          "songs": data["songs"], "materials": data["materials"] if is_music(me) else [],
                          "acknowledgements": acks,
                          "recipients": [{"id": m["id"], "name": m["name"], "part": m["part"]} for m in recipients] if me["role"] == "conductor" else [],
                          "required_materials": [m["id"] for m in required] if is_music(me) else [],
                          "missing_materials": missing, "missing_photos": [e["id"] for e in events if missing_photo(e)] if can_photo(me) else [],
                          "stats": stats, "finance": self.finance(data, selected), "stale": False, "loaded_at": now()}
                eligible = [e for e in events if e["category"] == "지휘" and not cancelled(e)]
                result["boards"] = {e["id"]: self.board(data, me, e["id"]) for e in eligible} if me["role"] in ("conductor", "part_leader") else {}
                result["my_attendance"] = {e["id"]: self.effective(next((a for a in data["attendance"] if a["member"] == me["id"] and a["event"] == e["id"]), None), e) for e in eligible} if me["role"] != "conductor" else {}
                self.cache[(member_id, sid)] = copy.deepcopy(result)
                self.cache[(member_id, None)] = copy.deepcopy(result)
                return result
            except NotionUnavailable:
                cached = self.cache.get((member_id, semester))
                if not cached:
                    raise
                return {**copy.deepcopy(cached), "stale": True}

    def context(self, member_id):
        data = self.load()
        return data, self.member(data, member_id)

    def choose_part(self, data, me, body):
        # 파트 미정 단원이 로그인 직후 한 번만 고른다. 이후 변경은 지휘자가 노션에서 한다.
        require(not me["part"], "파트가 이미 정해져 있습니다. 변경은 지휘자에게 문의해 주세요")
        part = text(body, "part", True)
        if part not in db.VOCAL_PARTS:   # 반주자·지휘자는 본인이 고를 수 없다
            raise HTTPException(422, "파트를 선택해 주세요")
        self.store.set_part(me["id"], PART_KO[part])
        return {"part": part}

    def event_permission(self, me, event):
        require(me["role"] == "conductor" if event["category"] == "지휘" else me["admin_role"] == "head")

    def save_event(self, data, me, body, event_id=None):
        existing = find(data["events"], event_id) if event_id else None
        if existing:
            self.event_permission(me, existing)
            require(not cancelled(existing), "취소 처리된 일정은 변경할 수 없습니다")
            if body.get("edited_at") and body["edited_at"] != existing["edited_at"]:
                raise HTTPException(409, "다른 곳에서 일정이 수정되었습니다. 새 내용을 불러온 뒤 변경해 주세요")
        kind = text(body, "kind", True)
        if kind not in KINDS:
            raise HTTPException(422, "일정 유형을 선택해 주세요")
        category = "행정" if kind == "admin" else "지휘"
        self.event_permission(me, {"category": category})
        if existing and category != existing["category"]:
            raise HTTPException(422, "지휘·행정 분류는 변경할 수 없습니다")
        try:
            raw = text(body, "starts_at", True)
            all_day = bool(body.get("all_day")) and kind == "admin"
            if kind != "admin" and "T" not in raw:
                raise ValueError()
            start = db.to_kst_naive_iso(raw)
            end = db.to_kst_naive_iso(text(body, "ends_at") or raw)
            if end < start or (kind != "admin" and end[:10] != start[:10]):
                raise ValueError()
            if all_day:
                start, end = start[:10] + "T00:00:00", end[:10] + "T23:59:59"
        except ValueError:
            raise HTTPException(422, "일정 날짜와 시간을 확인해 주세요")
        semester = self.selected(data, body.get("semester"))
        if kind in ("regular", "external"):
            # songs 키가 없는 부분 수정은 '곡 없음'이 아니라 '곡 유지'다.
            songs = body["songs"] if "songs" in body else (existing["songs"] if existing else [])
        else:
            if existing and existing["songs"]:
                raise HTTPException(422, "공연 곡이 연결된 일정은 연습·행정으로 바꿀 수 없습니다. 먼저 곡을 비워 주세요")
            songs = []
        if not isinstance(songs, list) or len(songs) > 100 or len(set(songs)) != len(songs):
            raise HTTPException(422, "공연 곡은 중복 없이 최대 100곡까지 선택해 주세요")
        for song in songs:
            find(data["songs"], song)
        changes = {"title": text(body, "title", True, 150), "kind": KINDS[kind], "category": category,
                   "starts_at": start, "ends_at": end, "all_day": all_day, "place": text(body, "place"),
                   "description": text(body, "description", limit=10000), "songs": songs,
                   "song_order": packed(songs), "semester": semester["id"]}
        if not existing:
            changes.update(key=operation_key(body), status="open", created_by=me["name"], confirmations="{}", photo_meta="{}")
        return {"id": self.store.save("events", changes, event_id)}

    def remove_event(self, data, me, event_id, delete=False):
        event = find(data["events"], event_id)
        self.event_permission(me, event)
        self.store.save("events", {"status": "deleting" if delete else "cancelling"}, event_id)
        for a in data["attendance"]:
            if a["event"] == event_id:
                self.store.delete(a["id"])
        if delete:
            self.store.delete(event_id)
        else:
            self.store.save("events", {"status": "cancelled", "confirmations": "{}", "closed_at": ""}, event_id)
        return {"ok": True}

    def save_song(self, data, me, body, song_id=None):
        require(me["role"] == "conductor")
        if song_id:
            previous = find(data["songs"], song_id)
            if body.get("edited_at") and body["edited_at"] != previous["edited_at"]:
                raise HTTPException(409, "곡 정보가 변경되었습니다. 새로 불러와 주세요")
        changes = {"title": text(body, "title", True, 150), "composer": text(body, "composer"), "arranger": text(body, "arranger")}
        if not song_id:
            changes.update(key=operation_key(body), created_by=me["name"])
        return {"id": self.store.save("songs", changes, song_id)}

    def delete_material(self, data, me, material_id):
        require(me["role"] == "conductor")
        material = find(data["materials"], material_id)
        # Keep historical confirmation rows even when their source material is removed.
        self.store.delete(material["id"])
        return {"ok": True}

    def material_ack(self, data, me, material_id, semester_id, confirm=False):
        require(is_music(me))
        material = find(data["materials"], material_id)
        if not is_recipient(me):
            require(not confirm)
            return {"ok": True}   # 지휘자의 열람은 확인 기록으로 남기지 않는다 — 확인 인원/대상 인원 집계 오염 방지
        semester = self.selected(data, semester_id)
        key = f"ack:{semester['id']}:{material_id}:{me['id']}"
        existing = next((a for a in data["acknowledgements"] if a["key"] == key), None)
        if confirm:
            require(is_recipient(me))
            require(material_id in {m["id"] for m in self.wanted_materials(data, semester["id"])}, "현재 확인 대상 자료가 아닙니다")
            if not existing or not existing["opened_at"]:
                raise HTTPException(409, "먼저 파일을 열어 주세요")
        if not existing or not existing["confirmed_at"]:
            values = {"key": key, "title": f"{me['name']} · {material['title']}", "member": me["id"],
                      "member_name": me["name"], "semester": semester["id"], "material": material_id,
                      "opened_at": existing["opened_at"] if existing else now()}
            if confirm:
                values["confirmed_at"] = now()
            self.store.save("acknowledgements", values, existing["id"] if existing else None)
        return {"ok": True}

    def save_ledger(self, data, me, body, row_id=None):
        require(me["admin_role"] == "treasurer")
        if row_id:
            previous = find(data["ledger"], row_id)
            if body.get("edited_at") and body["edited_at"] != previous["edited_at"]:
                raise HTTPException(409, "회계 항목이 변경되었습니다. 새로 불러와 주세요")
        direction, category = text(body, "direction", True), text(body, "classification", True)
        if direction not in ("수입", "지출") or category not in self.store.ledger_categories:
            raise HTTPException(422, "장부의 구분·분류를 선택해 주세요")
        amount = body.get("amount")
        if isinstance(amount, bool) or not isinstance(amount, (float, int)) or not 0 < amount <= 10**12 or int(amount) != amount:
            raise HTTPException(422, "금액은 양의 정수(원)로 입력해 주세요")
        try:
            date = datetime.strptime(text(body, "date", True), "%Y-%m-%d").date().isoformat()
        except ValueError:
            raise HTTPException(422, "날짜를 확인해 주세요")
        semester = self.selected(data, body.get("semester"))
        values = {"title": text(body, "title", True, 150), "date": date, "direction": direction,
                  "classification": category, "amount": amount, "owner": text(body, "owner") or me["name"],
                  "note": text(body, "note"), "semester": semester["id"]}
        if not row_id:
            values["key"] = operation_key(body)
        return {"id": self.store.save("ledger", values, row_id)}

    def carry(self, data, me, semester_id, expected):
        require(me["admin_role"] == "treasurer")
        semester = find(data["semesters"], semester_id)
        require(bool(semester["previous"]), "첫 학기는 이월 대상이 아닙니다")
        amount = self.finance(data, semester)["carry_suggested"]
        if expected != amount:
            raise HTTPException(409, "잔액이 변경되었습니다. 새 금액을 확인해 주세요")
        self.store.save("semesters", {"carry": amount, "carry_at": now(), "carry_by": me["name"]}, semester_id)
        return {"ok": True}

    def close_semester(self, data, me, semester_id):
        require(me["admin_role"] == "head")
        old = find(data["semesters"], semester_id)
        if old["state"] == "closed":
            return {"id": self.current(data)["id"]}
        if old["id"] != self.current(data)["id"] and not old["transition_at"]:
            raise HTTPException(409, "현재 학기만 마감할 수 있습니다")
        cutoff = old["transition_at"] or now()
        self.store.save("semesters", {"transition_at": cutoff}, old["id"])
        year, half = next_semester(int(old["year"]), int(old["half"]))
        key = f"semester:{year}:{half}"
        new_id = self.store.save("semesters", {"key": key, "title": f"{year}년 {half}학기", "year": year,
                    "half": half, "state": "pending", "starts_at": cutoff, "previous": old["id"]})
        for event in data["events"]:
            if event["semester"] in (old["id"], new_id) and event["starts_at"] > cutoff:
                self.store.save("events", {"semester": new_id}, event["id"])
                for attendance in data["attendance"]:
                    if attendance["event"] == event["id"]:
                        self.store.save("attendance", {"semester": new_id}, attendance["id"])
        # Activate new first: reads can always choose an active semester, even after a lost response.
        self.store.save("semesters", {"state": "active"}, new_id)
        self.store.save("semesters", {"state": "closed", "ends_at": cutoff}, old["id"])
        self.store.ensure_semester_views({"id": new_id, "title": f"{year}년 {half}학기"})
        return {"id": new_id}

    def attendance_event(self, data, event_id):
        event = find(data["events"], event_id)
        if event["category"] != "지휘" or cancelled(event):
            raise HTTPException(409, "출석 대상 일정이 아닙니다")
        return event

    def effective(self, attendance, event):
        a = attendance or {}
        status, source = rules.effective_status(KO_STATUS.get(a.get("status")), a.get("source"),
                                                datetime.fromisoformat(event["starts_at"]), db.now_kst())
        return {"status": status, "source": source, "reason": a.get("reason"), "eta": a.get("eta")}

    def attendance_for(self, data, me, event_id, body=None, target_id=None):
        event = self.attendance_event(data, event_id)
        target = self.member(data, target_id or me["id"])
        require(target["role"] != "conductor", "지휘자는 출석 대상이 아닙니다")
        require(target["part"], "파트를 먼저 선택해 주세요")
        if target_id:
            require(me["role"] == "conductor" or (me["role"] == "part_leader" and me["part"] == target["part"] and target["part"] != "accompanist"))
        attendance = next((a for a in data["attendance"] if a["event"] == event_id and a["member"] == target["id"]), None)
        if body is None:
            return self.effective(attendance, event)
        if event["status"] != "open":
            raise HTTPException(409, "마감된 일정입니다. 지휘자가 재오픈할 수 있습니다")
        if not target_id and now() >= event["starts_at"]:
            raise HTTPException(403, "시작 후에는 파트장·지휘자만 수정할 수 있습니다")
        try:
            v = rules.validate_status_input(text(body, "status", True), text(body, "reason") or None, text(body, "eta") or None)
        except ValueError as exc:
            raise HTTPException(422, str(exc))
        values = {"title": target["name"], "key": f"attendance:{event_id}:{target['id']}", "event": event_id,
                  "practice_title": event["title"], "date": event["starts_at"],
                  "semester": event["semester"], "member": target["id"], "student_id": target["student_id"],
                  "part": PART_KO[target["part"]], "status": STATUS_KO[v["status"]], "reason": v["reason"],
                  "eta": v["eta"], "source": me["role"] if target_id else "member", "updated_at": now()}
        self.store.save("attendance", values, attendance["id"] if attendance else None)
        # Any correction invalidates the part's prior sign-off.
        confirmations = dict(event["confirmations"])
        confirmations.pop(target["part"], None)
        self.store.save("events", {"confirmations": packed(confirmations)}, event_id)
        return self.effective(values, event)

    def required_parts(self, data):
        return db.VOCAL_PARTS + (["accompanist"] if any(m["active"] and m["part"] == "accompanist" for m in data["members"]) else [])

    def board(self, data, me, event_id):
        require(me["role"] in ("conductor", "part_leader"))
        event = self.attendance_event(data, event_id)
        parts = self.required_parts(data) if me["role"] == "conductor" else [me["part"]]
        totals = dict.fromkeys(("present", "late", "absent", "unconfirmed"), 0)
        result = {}
        for part in parts:
            counts, members = totals.copy(), []
            counts = dict.fromkeys(counts, 0)
            for member in sorted(data["members"], key=lambda m: m["name"]):
                if not member["active"] or member["part"] != part or member["role"] == "conductor":
                    continue
                a = next((a for a in data["attendance"] if a["event"] == event_id and a["member"] == member["id"]), None)
                effective = self.effective(a, event)
                counts[effective["status"] or "unconfirmed"] += 1
                members.append({"member_id": member["id"], "name": member["name"], **effective})
            for k in counts:
                totals[k] += counts[k]
            result[part] = {"confirmed": part in event["confirmations"], "counts": counts, "members": members}
        return {"practice": {**event, "notion_synced_at": event["closed_at"]}, "parts": result, "totals": totals,
                "roster_warnings": list(self.store.roster_warnings) if me["role"] == "conductor" else []}

    def confirm_part(self, data, me, event_id, part):
        event = self.attendance_event(data, event_id)
        require(me["role"] == "conductor" or (me["role"] == "part_leader" and me["part"] == part and part != "accompanist"))
        if event["status"] != "open" or part not in self.required_parts(data):
            raise HTTPException(409, "파트를 확인할 수 없습니다")
        confirmations = {**event["confirmations"], part: {"at": now(), "by": me["name"]}}
        self.store.save("events", {"confirmations": packed(confirmations)}, event_id)
        return {"confirmed": True}

    def close_attendance(self, data, me, event_id, reopen=False):
        require(me["role"] == "conductor")
        event = self.attendance_event(data, event_id)
        if reopen:
            self.store.save("events", {"status": "open", "confirmations": "{}", "closed_at": ""}, event_id)
            return {"status": "open"}
        missing = [p for p in self.required_parts(data) if p not in event["confirmations"]]
        if missing:
            raise HTTPException(409, {"missing_parts": missing})
        for m in data["members"]:
            # 파트 미선택자는 현황판 어느 파트에도 없다 → 자동 결석 기록도 만들지 않는다
            if not m["active"] or m["role"] == "conductor" or not m["part"]:
                continue
            a = next((a for a in data["attendance"] if a["event"] == event_id and a["member"] == m["id"]), None)
            if not a or not a["status"]:
                self.store.save("attendance", {"title": m["name"], "key": f"attendance:{event_id}:{m['id']}",
                    "event": event_id, "practice_title": event["title"], "date": event["starts_at"],
                    "semester": event["semester"], "member": m["id"], "student_id": m["student_id"],
                    "part": PART_KO[m["part"]], "status": "결석", "source": "auto", "updated_at": now()}, a["id"] if a else None)
        self.store.save("events", {"status": "closed", "closed_at": now()}, event_id)
        return {"status": "closed"}
