"""
Google Sheets integration.

Uses a Google Cloud service account (JSON key) with gspread. The target
spreadsheet must be shared (Editor access) with the service account's
client_email.

Resilience:
- Retries transient API errors (network blips, rate limits) with backoff.
- If Sheets is completely unreachable, appends the booking to a local CSV
  fallback log instead of losing the booking, and flags it for manual sync.
- Idempotent on `call_id` + `appointment_id`: re-calls with the same
  appointment_id will not create duplicate rows.
"""
import csv
import os
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import gspread
from google.oauth2.service_account import Credentials
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from app.config import settings

logger = logging.getLogger("sheets_service")

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
]

HEADERS = [
    "appointment_id",
    "call_id",
    "caller_name",
    "caller_phone",
    "service_requested",
    "preferred_date",
    "preferred_time",
    "is_returning_patient",
    "insurance_provider",
    "status",
    "created_at_utc",
]

_client: Optional[gspread.Client] = None


class SheetsUnavailableError(Exception):
    pass


def _get_client() -> gspread.Client:
    global _client
    if _client is not None:
        return _client
    if not os.path.exists(settings.GOOGLE_SERVICE_ACCOUNT_FILE):
        raise SheetsUnavailableError(
            f"Service account file not found at {settings.GOOGLE_SERVICE_ACCOUNT_FILE}"
        )
    creds = Credentials.from_service_account_file(
        settings.GOOGLE_SERVICE_ACCOUNT_FILE, scopes=SCOPES
    )
    _client = gspread.authorize(creds)
    return _client


def _get_worksheet():
    client = _get_client()
    sh = client.open_by_key(settings.GOOGLE_SHEET_ID)
    try:
        ws = sh.worksheet(settings.GOOGLE_SHEET_TAB_NAME)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(
            title=settings.GOOGLE_SHEET_TAB_NAME, rows=1000, cols=len(HEADERS)
        )
        ws.append_row(HEADERS)
    # Ensure header row exists on first ever write.
    first_row = ws.row_values(1)
    if first_row != HEADERS:
        ws.insert_row(HEADERS, 1)
    return ws


@retry(
    reraise=True,
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    retry=retry_if_exception_type(Exception),
)
def _append_row_with_retry(ws, row: list):
    ws.append_row(row, value_input_option="USER_ENTERED")


def _row_exists(ws, appointment_id: str) -> bool:
    try:
        cell = ws.find(appointment_id, in_column=1)
        return cell is not None
    except gspread.exceptions.CellNotFound:
        return False
    except Exception:
        # Non-fatal: if the search itself fails, fall through and let the
        # append attempt happen (duplicate is rare and better than losing data).
        return False


def _write_local_fallback(row: dict):
    path = Path(settings.LOCAL_FALLBACK_LOG_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    file_exists = path.exists()
    with open(path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=HEADERS)
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)
    logger.warning("Google Sheets unavailable — booking written to local fallback log: %s", path)


def save_appointment(
    appointment_id: str,
    call_id: str,
    caller_name: str,
    caller_phone: str,
    service_requested: str,
    preferred_date: str,
    preferred_time: str,
    is_returning_patient: bool,
    insurance_provider: str,
) -> dict:
    """
    Returns {"persisted_to": "google_sheets" | "local_fallback", "appointment_id": str}
    Never raises — booking data must never be lost even if Sheets is down.
    """
    row_dict = {
        "appointment_id": appointment_id,
        "call_id": call_id,
        "caller_name": caller_name,
        "caller_phone": caller_phone,
        "service_requested": service_requested,
        "preferred_date": preferred_date,
        "preferred_time": preferred_time,
        "is_returning_patient": str(is_returning_patient),
        "insurance_provider": insurance_provider or "none",
        "status": "confirmed",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    row = [row_dict[h] for h in HEADERS]

    try:
        ws = _get_worksheet()
        if _row_exists(ws, appointment_id):
            logger.info("Appointment %s already exists in sheet — skipping duplicate write.", appointment_id)
            return {"persisted_to": "google_sheets", "appointment_id": appointment_id, "duplicate": True}
        _append_row_with_retry(ws, row)
        logger.info("Appointment %s saved to Google Sheets.", appointment_id)
        return {"persisted_to": "google_sheets", "appointment_id": appointment_id, "duplicate": False}
    except Exception as exc:
        logger.error("Failed to write to Google Sheets after retries: %s", exc, exc_info=True)
        _write_local_fallback(row_dict)
        return {"persisted_to": "local_fallback", "appointment_id": appointment_id, "duplicate": False}


def check_slot_taken(preferred_date: str, preferred_time: str) -> bool:
    """
    Best-effort double-booking check by scanning existing confirmed rows for
    the same date+time. Fails open (returns False / "not taken") if Sheets
    can't be reached, so we never block a booking due to a read error —
    the write path still de-dupes on appointment_id.
    """
    try:
        ws = _get_worksheet()
        records = ws.get_all_records()
        for r in records:
            if (
                str(r.get("preferred_date")) == preferred_date
                and str(r.get("preferred_time")) == preferred_time
                and str(r.get("status")) == "confirmed"
            ):
                return True
        return False
    except Exception as exc:
        logger.warning("Could not verify existing bookings (failing open): %s", exc)
        return False
