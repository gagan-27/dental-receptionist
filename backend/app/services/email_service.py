"""
Email confirmation service (SMTP). Works with Gmail (App Password), SendGrid
SMTP relay, or any standard SMTP provider — just change .env values.

Design choice: email failure must NEVER fail the booking itself. The
appointment is already safely persisted (Sheets or local fallback) before
this runs. We log failures and report `email_sent: false` back to Retell so
the agent can optionally tell the caller "you may not receive an email but
your appointment is confirmed."
"""
import smtplib
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from app.config import settings

logger = logging.getLogger("email_service")


def _build_message(to_email: str, subject: str, html_body: str, text_body: str) -> MIMEMultipart:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"{settings.SMTP_FROM_NAME} <{settings.SMTP_FROM_EMAIL}>"
    msg["To"] = to_email
    msg.attach(MIMEText(text_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))
    return msg


def _send(to_email: str, subject: str, html_body: str, text_body: str) -> bool:
    if not settings.SMTP_USERNAME or not settings.SMTP_PASSWORD:
        logger.warning("SMTP credentials not configured — skipping email send (dev mode).")
        return False
    try:
        msg = _build_message(to_email, subject, html_body, text_body)
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=10) as server:
            server.starttls()
            server.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
            server.sendmail(settings.SMTP_FROM_EMAIL, [to_email], msg.as_string())
        return True
    except Exception as exc:
        logger.error("Failed to send email to %s: %s", to_email, exc, exc_info=True)
        return False


def send_booking_confirmation(
    patient_email: str | None,
    caller_name: str,
    service_requested: str,
    preferred_date: str,
    preferred_time: str,
    appointment_id: str,
) -> bool:
    """
    NOTE: The Retell flow as designed collects phone, not email (voice calls
    rarely reliably capture email by ear). If you extend the flow to also
    collect email, pass it here. If patient_email is None, we send only the
    internal staff notification and report email_sent=False for the patient.
    """
    subject = f"Appointment Confirmed — {settings.CLINIC_NAME}"
    text_body = (
        f"Hi {caller_name},\n\n"
        f"Your appointment is confirmed:\n"
        f"Service: {service_requested}\n"
        f"Date: {preferred_date}\n"
        f"Time: {preferred_time}\n"
        f"Appointment ID: {appointment_id}\n\n"
        f"Please arrive 10 minutes early. Reply to this email or call us if you need to reschedule.\n\n"
        f"— {settings.CLINIC_NAME}"
    )
    html_body = f"""
    <div style="font-family:Arial,sans-serif;max-width:480px;margin:auto;">
      <h2 style="color:#1a73e8;">Appointment Confirmed</h2>
      <p>Hi {caller_name},</p>
      <p>Your appointment at <strong>{settings.CLINIC_NAME}</strong> is confirmed:</p>
      <table style="width:100%;border-collapse:collapse;">
        <tr><td style="padding:6px 0;"><strong>Service</strong></td><td>{service_requested}</td></tr>
        <tr><td style="padding:6px 0;"><strong>Date</strong></td><td>{preferred_date}</td></tr>
        <tr><td style="padding:6px 0;"><strong>Time</strong></td><td>{preferred_time}</td></tr>
        <tr><td style="padding:6px 0;"><strong>Appointment ID</strong></td><td>{appointment_id}</td></tr>
      </table>
      <p>Please arrive 10 minutes early. Call us if you need to reschedule.</p>
      <p style="color:#888;font-size:12px;">— {settings.CLINIC_NAME}</p>
    </div>
    """

    patient_sent = False
    if patient_email:
        patient_sent = _send(patient_email, subject, html_body, text_body)

    # Always notify internal front desk, regardless of patient email outcome.
    if settings.CLINIC_NOTIFY_EMAIL:
        internal_subject = f"[New Booking] {caller_name} — {service_requested} on {preferred_date} {preferred_time}"
        _send(settings.CLINIC_NOTIFY_EMAIL, internal_subject, html_body, text_body)

    return patient_sent
