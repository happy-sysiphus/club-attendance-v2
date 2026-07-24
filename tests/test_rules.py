from datetime import datetime

import pytest

from app import rules

START = datetime(2026, 7, 24, 19, 0)


def test_present_drops_extras():
    assert rules.validate_status_input("present", "사유", "19:30") == {
        "status": "present", "reason": None, "eta": None}


def test_late_requires_reason_and_eta():
    with pytest.raises(ValueError):
        rules.validate_status_input("late", None, "19:30")
    with pytest.raises(ValueError):
        rules.validate_status_input("late", "버스", None)
    with pytest.raises(ValueError):
        rules.validate_status_input("late", "버스", "25:99")
    assert rules.validate_status_input("late", "버스", "19:30") == {
        "status": "late", "reason": "버스", "eta": "19:30"}


def test_absent_reason_optional():
    assert rules.validate_status_input("absent", None, None)["reason"] is None
    assert rules.validate_status_input("absent", "시험", "19:30") == {
        "status": "absent", "reason": "시험", "eta": None}


def test_invalid_status_rejected():
    with pytest.raises(ValueError):
        rules.validate_status_input("vacation", None, None)


def test_effective_before_start_stays_null():
    assert rules.effective_status(None, None, START,
                                  datetime(2026, 7, 24, 18, 0)) == (None, None)


def test_effective_after_start_becomes_auto_absent():
    assert rules.effective_status(None, None, START,
                                  datetime(2026, 7, 24, 19, 0)) == ("absent", "auto")


def test_effective_keeps_existing_status():
    assert rules.effective_status("late", "member", START,
                                  datetime(2026, 7, 24, 20, 0)) == ("late", "member")


def test_attendance_rate():
    assert rules.attendance_rate(8, 1, 10) == 0.9
    assert rules.attendance_rate(0, 0, 0) == 0.0
