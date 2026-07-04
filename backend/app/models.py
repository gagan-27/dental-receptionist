"""
Pydantic schemas for all Retell custom-function webhook payloads.

RetellAI wraps custom function-tool calls in an envelope like:
{
  "call": { "call_id": "...", "from_number": "...", "to_number": "...", ... },
  "name": "check_availability",
  "args": { ...the parameters defined in the tool schema... }
}
We accept both the wrapped envelope and a flat body (for easy manual/curl testing),
via the `unwrap_retell_payload` helper in routers/retell_functions.py.
"""
from pydantic import BaseModel, Field, field_validator
from typing import Optional, List
import re


class CheckAvailabilityArgs(BaseModel):
    service_requested: str
    preferred_date: str = Field(..., description="YYYY-MM-DD")
    preferred_time: str = Field(..., description="HH:MM, 24h")

    @field_validator("preferred_date")
    @classmethod
    def validate_date(cls, v: str) -> str:
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", v):
            raise ValueError("preferred_date must be in YYYY-MM-DD format")
        return v

    @field_validator("preferred_time")
    @classmethod
    def validate_time(cls, v: str) -> str:
        if not re.match(r"^([01]\d|2[0-3]):[0-5]\d$", v):
            raise ValueError("preferred_time must be in HH:MM 24-hour format")
        return v


class AvailabilityResponse(BaseModel):
    available: bool
    reason: Optional[str] = None
    suggested_slots: List[str] = Field(default_factory=list)


class BookAppointmentArgs(BaseModel):
    caller_name: str
    caller_phone: str
    service_requested: str
    preferred_date: str
    preferred_time: str
    is_returning_patient: Optional[bool] = False
    insurance_provider: Optional[str] = "none"
    call_id: str

    @field_validator("caller_phone")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        digits = re.sub(r"\D", "", v)
        if len(digits) < 7:
            raise ValueError("caller_phone does not look like a valid phone number")
        return v

    @field_validator("caller_name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        if not v or len(v.strip()) < 2:
            raise ValueError("caller_name is required")
        return v.strip()


class BookAppointmentResponse(BaseModel):
    success: bool
    appointment_id: Optional[str] = None
    message: str
    email_sent: bool = False
    webhook_sent: bool = False


class EscalationArgs(BaseModel):
    caller_name: Optional[str] = None
    caller_phone: Optional[str] = None
    reason: str
    call_id: str


class HealthResponse(BaseModel):
    status: str
    app_env: str

class SendConfirmationEmailArgs(BaseModel):
    appointment_id: str
    caller_name: str
    caller_email: Optional[str] = None
    service_requested: str
    preferred_date: str
    preferred_time: str

    @field_validator("caller_email")
    @classmethod
    def validate_email(cls, v: Optional[str]) -> Optional[str]:
        if v is None or v.strip() == "" or v.strip().lower() in ("none", "n/a", "not provided"):
            return None
        v = v.strip()
        if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", v):
            return None
        return v


class SendConfirmationEmailResponse(BaseModel):
    success: bool
    email_sent: bool
    message: str
