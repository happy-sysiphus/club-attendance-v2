import logging
import os
import tempfile
from pathlib import Path
from urllib.parse import unquote

from fastapi import Body, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse
from starlette.concurrency import run_in_threadpool

from . import auth, config
from .operations import Operations, can_photo, find, is_music, now, operation_key, packed, require, text
from .operations_store import NotionUnavailable, OperationsStore

MIMES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".heic": "image/heic",
         ".pdf": "application/pdf", ".mp3": "audio/mpeg", ".m4a": "audio/mp4", ".wav": "audio/wav"}


def install(app, notion, conn):
    operations = Operations(OperationsStore(notion, conn)) if notion else None
    app.state.operations = operations

    @app.exception_handler(NotionUnavailable)
    async def notion_error(request, exc):
        logging.getLogger("attendance").warning("Notion operation failed: %s", exc)
        return JSONResponse({"detail": str(exc)}, status_code=503)

    @app.middleware("http")
    async def api_headers(request, call_next):
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            origin = request.headers.get("origin")
            if origin and origin.rstrip("/") != str(request.base_url).rstrip("/"):
                return JSONResponse({"detail": "허용되지 않은 요청 출처"}, status_code=403)
        response = await call_next(request)
        if request.url.path.startswith(("/api/", "/auth/", "/practices", "/me/")):
            response.headers["Cache-Control"] = "no-store"
        return response

    def available():
        if operations is None:
            raise NotionUnavailable("NOTION_TOKEN과 NOTION_PARENT_PAGE_ID를 설정해 주세요. 저장되지 않은 상태로 운영할 수 없습니다.")
        return operations

    def identity(request: Request):
        available()
        token = request.cookies.get("session")
        member_id = auth.verify_token(token, config.SECRET_KEY) if token else None
        if not member_id:
            raise HTTPException(401, "로그인 필요")
        return member_id

    def execute(member_id, function, *args, **kwargs):
        ops = available()
        with ops.store.lock:
            data, me = ops.context(member_id)
            return function(data, me, *args, **kwargs)

    @app.post("/auth/login")
    def login(request: Request, response: Response, body: dict = Body(...)):
        ops = available()
        with ops.store.lock:
            ops.store.bootstrap()
            members = ops.store.roster()
            me = next((m for m in members if m["active"] and m["name"] == text(body, "name", True)
                       and m["student_id"] == text(body, "student_id", True)), None)
            if not me:
                raise HTTPException(401, "명단에 없습니다")
            response.set_cookie("session", auth.sign_token(me["id"], config.SECRET_KEY), httponly=True,
                                secure=request.url.scheme == "https", samesite="lax", max_age=60*60*24*180)
            return {k: v for k, v in me.items() if k != "student_id"}

    @app.post("/auth/logout")
    def logout(response: Response):
        response.delete_cookie("session")
        return {"ok": True}

    @app.get("/api/state")
    def state(semester: str | None = None, fresh: bool = False, member_id=Depends(identity)):
        return available().snapshot(member_id, semester, fresh)

    @app.post("/api/me/part")
    def choose_part(body: dict = Body(...), member_id=Depends(identity)):
        return execute(member_id, operations.choose_part, body)

    @app.post("/api/events", status_code=201)
    def event_create(body: dict = Body(...), member_id=Depends(identity)):
        return execute(member_id, operations.save_event, body)

    @app.put("/api/events/{event_id}")
    def event_update(event_id: str, body: dict = Body(...), member_id=Depends(identity)):
        return execute(member_id, operations.save_event, body, event_id)

    @app.delete("/api/events/{event_id}")
    def event_delete(event_id: str, member_id=Depends(identity)):
        return execute(member_id, operations.remove_event, event_id, True)

    @app.post("/api/events/{event_id}/cancel")
    def event_cancel(event_id: str, member_id=Depends(identity)):
        return execute(member_id, operations.remove_event, event_id)

    @app.post("/api/events/{event_id}/songs")
    def event_song(event_id: str, body: dict = Body(...), member_id=Depends(identity)):
        def linking(data, me):
            from .operations import performance, cancelled
            require(me["role"] == "conductor")
            event = find(data["events"], event_id)
            song = find(data["songs"], body.get("song_id"))
            require(performance(event) and not cancelled(event), "곡을 연결할 수 없는 일정입니다")
            songs = list(event["songs"])
            if song["id"] not in songs:
                songs.append(song["id"])
            if len(songs) > 100:
                raise HTTPException(422, "공연당 최대 100곡까지 선택할 수 있습니다")
            operations.store.save("events", {"songs": songs, "song_order": packed(songs)}, event_id)
            return {"ok": True}
        return execute(member_id, linking)

    @app.post("/api/songs", status_code=201)
    def song_create(body: dict = Body(...), member_id=Depends(identity)):
        return execute(member_id, operations.save_song, body)

    @app.put("/api/songs/{song_id}")
    def song_update(song_id: str, body: dict = Body(...), member_id=Depends(identity)):
        return execute(member_id, operations.save_song, body, song_id)

    @app.put("/api/materials/{material_id}")
    def material_update(material_id: str, body: dict = Body(...), member_id=Depends(identity)):
        def update(data, me):
            require(me["role"] == "conductor")
            find(data["materials"], material_id)
            if not isinstance(body.get("required"), bool):
                raise HTTPException(422, "확인 필수 여부를 선택해 주세요")
            operations.store.save("materials", {"required": body["required"], "title": text(body, "title", True, 150)}, material_id)
            return {"ok": True}
        return execute(member_id, update)

    @app.delete("/api/materials/{material_id}")
    def material_delete(material_id: str, member_id=Depends(identity)):
        return execute(member_id, operations.delete_material, material_id)

    @app.post("/api/materials/{material_id}/confirm")
    def material_confirm(material_id: str, body: dict = Body(...), member_id=Depends(identity)):
        return execute(member_id, operations.material_ack, material_id, body.get("semester"), True)

    @app.get("/api/materials/{material_id}/open")
    def material_open(material_id: str, semester: str | None = None, member_id=Depends(identity)):
        def opening(data, me):
            require(is_music(me))
            material = find(data["materials"], material_id)
            operations.material_ack(data, me, material_id, semester)
            if not material["files"]:
                raise HTTPException(404, "파일이 없습니다")
            f = material["files"][0]
            url = f.get(f.get("type"), {}).get("url", "")
            if not url.startswith("https://"):
                raise HTTPException(409, "파일 URL을 다시 불러와 주세요")
            return RedirectResponse(url, status_code=303)
        return execute(member_id, opening)

    @app.delete("/api/events/{event_id}/photos/{filename}")
    def photo_delete(event_id: str, filename: str, member_id=Depends(identity)):
        def removing(data, me):
            require(can_photo(me))
            event = find(data["events"], event_id)
            remaining = [f for f in event["photos"] if f["name"] != filename]
            meta = {k: v for k, v in event["photo_meta"].items() if k != filename}
            operations.store.save("events", {"photos": writable_files(remaining), "photo_meta": packed(meta)}, event_id)
            return {"ok": True}
        return execute(member_id, removing)

    @app.post("/api/upload/{target}/{target_id}")
    async def upload(target: str, target_id: str, request: Request, member_id=Depends(identity)):
        if target not in ("photos", "materials"):
            raise HTTPException(404)
        filename = Path(unquote(request.headers.get("x-filename", ""))).name.replace("\\", "_")
        suffix = Path(filename).suffix.lower()
        kind = request.headers.get("x-material-kind", "score")
        allowed = {".jpg", ".jpeg", ".png", ".heic"} if target == "photos" else (
                  {".pdf", ".jpg", ".jpeg", ".png", ".heic"} if kind == "score" else {".mp3", ".m4a", ".wav"})
        if suffix not in allowed or kind not in ("score", "audio") or len(filename) > 150:
            raise HTTPException(422, "지원하는 파일 형식과 파일명을 확인해 주세요")
        key = operation_key({"request_id": request.headers.get("x-request-id", "")})
        limit = int(os.environ.get("MAX_UPLOAD_MB", "200")) * 1024 * 1024
        with tempfile.SpooledTemporaryFile(max_size=5 * 1024 * 1024) as file:
            size = 0
            async for chunk in request.stream():
                size += len(chunk)
                if size > limit:
                    raise HTTPException(413, f"파일당 {limit // 1024 // 1024}MB까지 업로드할 수 있습니다")
                file.write(chunk)
            if not size:
                raise HTTPException(422, "빈 파일입니다")
            file.seek(0)
            stored_name = f"{key}--{filename}" if target == "photos" else filename
            rehearsal_date = request.headers.get("x-rehearsal-date", "")
            if target == "materials" and rehearsal_date:
                from datetime import date
                try:
                    date.fromisoformat(rehearsal_date)
                except ValueError:
                    raise HTTPException(422, "연습 날짜를 확인해 주세요")

            def check(data, me):
                # 잠금 안 1단계: 권한·대상·중복만 확인한다 (빠름). 바이트 전송은 잠금 밖에서 한다.
                if target == "photos":
                    require(can_photo(me))
                    event = find(data["events"], target_id)
                    if any(f["name"] == stored_name for f in event["photos"]):
                        return {"ok": True}
                    if len(event["photos"]) >= 100:
                        raise HTTPException(422, "일정당 사진은 최대 100장입니다")
                    return None
                require(me["role"] == "conductor")
                find(data["songs"], target_id)
                found = next((m for m in data["materials"] if m["key"] == key), None)
                return {"id": found["id"]} if found else None

            done = await run_in_threadpool(execute, member_id, check)
            if done:
                return done
            # 잠금 밖: 대용량 전송(수 초~수 분) 동안 다른 단원의 출석 입력·조회가 막히지 않는다.
            attachment = await run_in_threadpool(operations.store.upload, file, stored_name, MIMES[suffix], size)

            def persist(data, me):
                # 잠금 안 2단계: 최신 상태를 다시 읽어 중복·권한을 재확인한 뒤 속성만 저장한다 (0.35초).
                if target == "photos":
                    require(can_photo(me))
                    event = find(data["events"], target_id)
                    if any(f["name"] == stored_name for f in event["photos"]):
                        return {"ok": True}
                    replacement = unquote(request.headers.get("x-replace-photo", ""))
                    remaining = [f for f in event["photos"] if f["name"] != replacement]
                    if len(remaining) >= 100:
                        raise HTTPException(422, "일정당 사진은 최대 100장입니다")
                    metadata = {k: v for k, v in event["photo_meta"].items() if k != replacement}
                    metadata[stored_name] = {"by": me["name"], "member": me["id"], "at": now()}
                    operations.store.save("events", {"photos": writable_files(remaining) + [attachment], "photo_meta": packed(metadata)}, target_id)
                    return {"ok": True}
                require(me["role"] == "conductor")
                song = find(data["songs"], target_id)
                found = next((m for m in data["materials"] if m["key"] == key), None)
                if found:
                    return {"id": found["id"]}
                saved = operations.store.save("materials", {"key": key, "title": filename, "song": song["id"],
                    "kind": kind, "required": request.headers.get("x-required", "true" if kind == "score" else "false") == "true",
                    "files": [attachment], "uploaded_at": now(), "created_by": me["name"], "rehearsal_date": rehearsal_date})
                return {"id": saved}   # 최초 성공과 재시도가 같은 형태를 돌려준다
            return await run_in_threadpool(execute, member_id, persist)

    @app.post("/api/ledger", status_code=201)
    def ledger_create(body: dict = Body(...), member_id=Depends(identity)):
        return execute(member_id, operations.save_ledger, body)

    @app.put("/api/ledger/{row_id}")
    def ledger_update(row_id: str, body: dict = Body(...), member_id=Depends(identity)):
        return execute(member_id, operations.save_ledger, body, row_id)

    @app.delete("/api/ledger/{row_id}")
    def ledger_delete(row_id: str, member_id=Depends(identity)):
        def removing(data, me):
            require(me["admin_role"] == "treasurer")
            operations.store.delete(find(data["ledger"], row_id)["id"])
            return {"ok": True}
        return execute(member_id, removing)

    @app.post("/api/semesters/{semester_id}/carry")
    def carry(semester_id: str, body: dict = Body(...), member_id=Depends(identity)):
        return execute(member_id, operations.carry, semester_id, body.get("amount"))

    @app.post("/api/semesters/{semester_id}/close")
    def semester_close(semester_id: str, member_id=Depends(identity)):
        return execute(member_id, operations.close_semester, semester_id)

    # Retain the established attendance URLs and rule behavior; IDs are now durable Notion IDs.
    @app.get("/practices")
    def practices(semester: str | None = None, member_id=Depends(identity)):
        snapshot = operations.snapshot(member_id, semester)
        return [e for e in snapshot["events"] if e["category"] == "지휘" and e["status"] not in ("cancelled", "cancelling", "deleting")]

    @app.get("/me/stats")
    def stats(semester: str | None = None, member_id=Depends(identity)):
        return operations.snapshot(member_id, semester)["stats"]

    @app.get("/practices/{event_id}/me")
    def attendance_get(event_id: str, member_id=Depends(identity)):
        return execute(member_id, operations.attendance_for, event_id)

    @app.put("/practices/{event_id}/me")
    def attendance_put(event_id: str, body: dict = Body(...), member_id=Depends(identity)):
        return execute(member_id, operations.attendance_for, event_id, body)

    @app.get("/practices/{event_id}/board")
    def board(event_id: str, member_id=Depends(identity)):
        return execute(member_id, operations.board, event_id)

    @app.put("/practices/{event_id}/members/{target_id}")
    def attendance_staff(event_id: str, target_id: str, body: dict = Body(...), member_id=Depends(identity)):
        return execute(member_id, operations.attendance_for, event_id, body, target_id)

    @app.post("/practices/{event_id}/part/confirm")
    def part_confirm(event_id: str, body: dict = Body(...), member_id=Depends(identity)):
        return execute(member_id, operations.confirm_part, event_id, body.get("part"))

    @app.post("/practices/{event_id}/close")
    def close(event_id: str, member_id=Depends(identity)):
        return execute(member_id, operations.close_attendance, event_id)

    @app.post("/practices/{event_id}/reopen")
    def reopen(event_id: str, member_id=Depends(identity)):
        return execute(member_id, operations.close_attendance, event_id, True)


def writable_files(files):
    result = []
    for f in files:
        typ = f["type"]
        if typ in ("file", "external"):
            result.append({"name": f["name"], "type": typ, typ: {"url": f[typ]["url"]}})
        else:
            result.append(f)
    return result
