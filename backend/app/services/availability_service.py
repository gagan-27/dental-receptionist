"""
Business-rule layer for clinic hours + slot suggestion.
Kept dependency-free from Sheets so it can be unit-tested in isolation.
"""
from datetime import datetime, timedelta
import logging

from app.config import settings, VALID_SERVICES
from app.models import AvailabilityResponse
from app.services import sheets_service

logger = logging.getLogger("availability_service")


def _parse_datetime(date_str: str, time_str: str) -> datetime:
    return datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")


def _is_within_working_hours(dt: datetime) -> tuple[bool, str]:
    if dt.weekday() == settings.CLINIC_CLOSED_WEEKDAY:
        return False, "The clinic is closed on Sundays."
    if dt < datetime.now():
        return False, "That date/time is in the past."
    hour_minute = dt.hour + dt.minute / 60
    if hour_minute < settings.CLINIC_OPEN_HOUR or hour_minute >= settings.CLINIC_CLOSE_HOUR:
        return False, (
            f"The clinic is open {settings.CLINIC_OPEN_HOUR}:00 AM to "
            f"{settings.CLINIC_CLOSE_HOUR - 12}:00 PM, Monday to Saturday."
        )
    return True, ""


def _suggest_alternative_slots(dt: datetime, count: int = 3) -> list[str]:
    """Suggest the next `count` valid same-day/next-days slots, skipping Sundays."""
    suggestions = []
    cursor = dt
    step = timedelta(minutes=settings.SLOT_DURATION_MINUTES)
    attempts = 0
    max_attempts = 200  # safety bound
    while len(suggestions) < count and attempts < max_attempts:
        cursor += step
        attempts += 1
        ok, _ = _is_within_working_hours(cursor)
        if not ok:
            # jump to next day 9 AM if we've walked past closing / hit Sunday
            next_day = (cursor + timedelta(days=1)).replace(
                hour=settings.CLINIC_OPEN_HOUR, minute=0, second=0, microsecond=0
            )
            cursor = next_day
            continue
        if not sheets_service.check_slot_taken(cursor.strftime("%Y-%m-%d"), cursor.strftime("%H:%M")):
            suggestions.append(cursor.strftime("%Y-%m-%d %H:%M"))
    return suggestions


def check_availability(service_requested: str, preferred_date: str, preferred_time: str) -> AvailabilityResponse:
    if service_requested not in VALID_SERVICES:
        return AvailabilityResponse(
            available=False,
            reason=f"'{service_requested}' is not a service we currently offer.",
            suggested_slots=[],
        )

    try:
        dt = _parse_datetime(preferred_date, preferred_time)
    except ValueError:
        return AvailabilityResponse(
            available=False,
            reason="I couldn't understand that date/time — could you repeat it?",
            suggested_slots=[],
        )

    within_hours, reason = _is_within_working_hours(dt)
    if not within_hours:
        alternatives = _suggest_alternative_slots(dt)
        return AvailabilityResponse(available=False, reason=reason, suggested_slots=alternatives)

    taken = sheets_service.check_slot_taken(preferred_date, preferred_time)
    if taken:
        alternatives = _suggest_alternative_slots(dt)
        return AvailabilityResponse(
            available=False,
            reason="That slot is already booked.",
            suggested_slots=alternatives,
        )

    return AvailabilityResponse(available=True, reason=None, suggested_slots=[])
