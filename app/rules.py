import re
from datetime import datetime

ETA_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
STATUSES = {"present", "late", "absent"}


def validate_status_input(status, reason, eta):
    if status not in STATUSES:
        raise ValueError("status는 present/late/absent 중 하나")
    if status == "present":
        return {"status": "present", "reason": None, "eta": None}
    if status == "late":
        if not reason:
            raise ValueError("지각은 사유 필수")
        if not eta or not ETA_RE.match(eta):
            raise ValueError("지각은 예상 도착 시간(HH:MM) 필수")
        return {"status": "late", "reason": reason, "eta": eta}
    return {"status": "absent", "reason": reason or None, "eta": None}


def effective_status(status, source, starts_at: datetime, now: datetime):
    if status is None and now >= starts_at:
        return "absent", "auto"
    return status, source


def attendance_rate(present: int, late: int, total: int) -> float:
    return round((present + late) / total, 3) if total else 0.0
