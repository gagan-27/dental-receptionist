import hashlib
import hmac
import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Request, HTTPException, Header
from pydantic import ValidationError

from app.config import settings
from app.models import (
    CheckAvailabilityArgs,
    AvailabilityResponse,
    BookAppointmentArgs,
    BookAppointmentResponse,
    EscalationArgs,
    SendConfirmationEmailArgs,
    SendConfirmationEmailResponse,
)
from app.services import availability_service, sheets_service, email_service, webhook_service

logger = logging.getLogger("retell_functions")
router = APIRouter(prefix="/webhook", tags=["retell-functions"])


def _unwrap_retell_payload(body: dict) -> dict:
    """
    RetellAI wraps custom-function args as {"call": {...}, "name": "...", "args": {...}}.
    Accept that shape, or a flat body (useful for local curl testing).
    """
    if isinstance(body, dict) and "args" in body and isinstance(body["args"], dict):
        flat = dict(body["args"])
        if "call" in body and isinstance(body["call"], dict):
            flat.setdefault("call_id", body["call"].get("call_id"))
        return flat
    return body


def _verify_signature(raw_body: bytes, signature_header: str | None):
    if not settings.VERIFY_RETELL_SIGNATURE:
        return
    if not signature_header or not settings.RETELL_WEBHOOK_SIGNING_SECRET:
        raise HTTPException(status_code=401, detail="Missing or unconfigured webhook signature.")
    expected = hmac.new(
        settings.RETELL_WEBHOOK_SIGNING_SECRET.encode(), raw_body, hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(expected, signature_header):
        raise HTTPException(status_code=401, detail="Invalid webhook signature.")


@router.post("/check-availability", response_model=AvailabilityResponse)
async def check_availability(request: Request, x_retell_signature: str | None = Header(default=None)):
    raw = await request.body()
    _verify_signature(raw, x_retell_signature)

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body.")

    flat = _unwrap_retell_payload(body)
    try:
        args = CheckAvailabilityArgs(**flat)
    except ValidationError as e:
        logger.warning("check-availability validation error: %s", e)
        # Return a graceful, agent-speakable response rather than a raw 422 —
        # the flow's fallback branch reads `available: false` + reason.
        return AvailabilityResponse(available=False, reason="I couldn't understand that date or time — could you say it again?", suggested_slots=[])

    result = availability_service.check_availability(
        args.service_requested, args.preferred_date, args.preferred_time
    )
    logger.info("check-availability: %s -> %s", flat, result)
    return result


@router.post("/book-appointment", response_model=BookAppointmentResponse)
async def book_appointment(request: Request, x_retell_signature: str | None = Header(default=None)):
    raw = await request.body()
    _verify_signature(raw, x_retell_signature)

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body.")

    flat = _unwrap_retell_payload(body)
    try:
        args = BookAppointmentArgs(**flat)
    except ValidationError as e:
        logger.warning("book-appointment validation error: %s", e)
        return BookAppointmentResponse(
            success=False,
            message="I'm missing some details to complete the booking — could we go through that again?",
        )

    # Re-validate availability server-side (defense in depth — the caller's
    # earlier check-availability call could be stale if seconds passed).
    availability = availability_service.check_availability(
        args.service_requested, args.preferred_date, args.preferred_time
    )
    if not availability.available:
        return BookAppointmentResponse(
            success=False,
            message=availability.reason or "That slot is no longer available.",
        )

    appointment_id = f"APT-{uuid.uuid4().hex[:8].upper()}"

    save_result = sheets_service.save_appointment(
        appointment_id=appointment_id,
        call_id=args.call_id,
        caller_name=args.caller_name,
        caller_phone=args.caller_phone,
        service_requested=args.service_requested,
        preferred_date=args.preferred_date,
        preferred_time=args.preferred_time,
        is_returning_patient=bool(args.is_returning_patient),
        insurance_provider=args.insurance_provider or "none",
    )

    email_sent = email_service.send_booking_confirmation(
        patient_email=None,  # flow currently collects phone only; wire up if email is added
        caller_name=args.caller_name,
        service_requested=args.service_requested,
        preferred_date=args.preferred_date,
        preferred_time=args.preferred_time,
        appointment_id=appointment_id,
    )

    webhook_sent = webhook_service.send_booking_webhook(
        {
            "event": "appointment_booked",
            "appointment_id": appointment_id,
            "call_id": args.call_id,
            "caller_name": args.caller_name,
            "caller_phone": args.caller_phone,
            "service_requested": args.service_requested,
            "preferred_date": args.preferred_date,
            "preferred_time": args.preferred_time,
            "insurance_provider": args.insurance_provider,
            "persisted_to": save_result["persisted_to"],
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
        }
    )

    logger.info(
        "Booking %s complete. persisted_to=%s email_sent=%s webhook_sent=%s",
        appointment_id, save_result["persisted_to"], email_sent, webhook_sent,
    )

    return BookAppointmentResponse(
        success=True,
        appointment_id=appointment_id,
        message="Appointment confirmed.",
        email_sent=email_sent,
        webhook_sent=webhook_sent,
    )


"""@router.post("/escalate")
async def escalate(request: Request, x_retell_signature: str | None = Header(default=None)):
    
    Optional: called (or logged) when the flow transfers to a human, so
    front-desk staff get a heads-up even if the live transfer fails
    (e.g., line busy). Wire this to node_human_transfer's edges in Retell
    if you want an explicit function call before/alongside the transfer_call
    node; as designed, the flow relies on transfer_call's handoff_message,
    and this endpoint is a supplementary audit trail.
    
    raw = await request.body()
    _verify_signature(raw, x_retell_signature)

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body.")

    flat = _unwrap_retell_payload(body)
    try:
        args = EscalationArgs(**flat)
    except ValidationError as e:
        logger.warning("escalate validation error: %s", e)
        raise HTTPException(status_code=422, detail=str(e))

    webhook_service.send_escalation_webhook(
        {
            "event": "call_escalated",
            "call_id": args.call_id,
            "caller_name": args.caller_name,
            "caller_phone": args.caller_phone,
            "reason": args.reason,
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
        }
    )
    logger.info("Escalation logged for call %s: %s", args.call_id, args.reason)
    return {"acknowledged": True}"""

@router.post("/send-confirmation-email", response_model=SendConfirmationEmailResponse)
async def send_confirmation_email(request: Request, x_retell_signature: str | None = Header(default=None)):
    """
    Called from the flow AFTER book_appointment has already succeeded, once
    the caller has separately been asked for and confirmed their email
    address. Kept as its own endpoint (rather than folding into
    book-appointment) so the booking itself never depends on email at all —
    the appointment is already fully saved by the time this runs. If the
    caller declines to give an email, the flow shouldn't call this at all;
    if it's called with no email anyway, we no-op cleanly rather than error.
    """
    raw = await request.body()
    _verify_signature(raw, x_retell_signature)
 
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body.")
 
    flat = _unwrap_retell_payload(body)
    try:
        args = SendConfirmationEmailArgs(**flat)
    except ValidationError as e:
        logger.warning("send-confirmation-email validation error: %s", e)
        return SendConfirmationEmailResponse(
            success=False, email_sent=False, message="Missing required booking details to send the confirmation email."
        )
 
    if not args.caller_email:
        logger.info("send-confirmation-email called with no usable email for appointment %s — skipping.", args.appointment_id)
        return SendConfirmationEmailResponse(
            success=True, email_sent=False, message="No email provided; nothing sent."
        )
 
    email_sent = email_service.send_booking_confirmation(
        patient_email=args.caller_email,
        caller_name=args.caller_name,
        service_requested=args.service_requested,
        preferred_date=args.preferred_date,
        preferred_time=args.preferred_time,
        appointment_id=args.appointment_id,
    )
 
    logger.info(
        "send-confirmation-email for appointment %s to %s: email_sent=%s",
        args.appointment_id, args.caller_email, email_sent,
    )
 
    return SendConfirmationEmailResponse(
        success=True,
        email_sent=email_sent,
        message="Confirmation email sent." if email_sent else "Booking is confirmed, but the email could not be sent.",
    )
