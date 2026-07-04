"""
Fires an outbound webhook (Slack, CRM, n8n, Zapier/Make catch hook, internal
system, etc.) after a successful booking. Independent of the email path —
either can fail without affecting the other, and neither affects the
already-persisted Sheets record.
"""
import logging
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import settings

logger = logging.getLogger("webhook_service")


@retry(
    reraise=True,
    stop=stop_after_attempt(settings.WEBHOOK_MAX_RETRIES if settings.WEBHOOK_MAX_RETRIES > 0 else 1),
    wait=wait_exponential(multiplier=1, min=1, max=6),
)
def _post_with_retry(url: str, payload: dict, timeout: int):
    resp = httpx.post(url, json=payload, timeout=timeout)
    resp.raise_for_status()
    return resp


def send_booking_webhook(payload: dict) -> bool:
    if not settings.CONFIRMATION_WEBHOOK_URL:
        logger.info("CONFIRMATION_WEBHOOK_URL not set — skipping outbound webhook.")
        return False
    try:
        _post_with_retry(
            settings.CONFIRMATION_WEBHOOK_URL, payload, settings.WEBHOOK_TIMEOUT_SECONDS
        )
        logger.info("Booking webhook delivered to %s", settings.CONFIRMATION_WEBHOOK_URL)
        return True
    except Exception as exc:
        logger.error("Booking webhook failed after retries: %s", exc, exc_info=True)
        return False


"""def send_escalation_webhook(payload: dict) -> bool:
    Same target URL, distinguished by payload['event'] — swap for a
    dedicated ESCALATION_WEBHOOK_URL env var if you want a different channel.
    if not settings.CONFIRMATION_WEBHOOK_URL:
        return False
    try:
        _post_with_retry(
            settings.CONFIRMATION_WEBHOOK_URL, payload, settings.WEBHOOK_TIMEOUT_SECONDS
        )
        return True
    except Exception as exc:
        logger.error("Escalation webhook failed: %s", exc, exc_info=True)
        return False"""
