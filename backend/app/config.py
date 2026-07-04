"""
Centralized configuration loaded from environment variables.
Copy .env.example to .env and fill in real values before running.
"""
from pydantic_settings import BaseSettings
from pydantic import Field
from typing import Optional


class Settings(BaseSettings):
    # --- App ---
    APP_ENV: str = Field(default="development")
    LOG_LEVEL: str = Field(default="INFO")

    # --- Retell ---
    RETELL_API_KEY: Optional[str] = Field(default=None)
    RETELL_WEBHOOK_SIGNING_SECRET: Optional[str] = Field(
        default=None,
        description="Used to verify X-Retell-Signature header on incoming function-call webhooks.",
    )
    VERIFY_RETELL_SIGNATURE: bool = Field(default=False)

    # --- Google Sheets ---
    GOOGLE_SERVICE_ACCOUNT_FILE: str = Field(default="credentials/google_service_account.json")
    GOOGLE_SHEET_ID: str = Field(default="")
    GOOGLE_SHEET_TAB_NAME: str = Field(default="Appointments")

    # --- Email (SMTP) ---
    SMTP_HOST: str = Field(default="smtp.gmail.com")
    SMTP_PORT: int = Field(default=587)
    SMTP_USERNAME: str = Field(default="")
    SMTP_PASSWORD: str = Field(default="")
    SMTP_FROM_EMAIL: str = Field(default="no-reply@quensultingai-dental.com")
    SMTP_FROM_NAME: str = Field(default="QuensultingAI Dental Clinic")
    CLINIC_NOTIFY_EMAIL: str = Field(
        default="frontdesk@quensultingai-dental.com",
        description="Internal staff email that also gets a copy of every new booking.",
    )

    # --- Outbound confirmation webhook (Slack / CRM / Make / n8n, etc.) ---
    CONFIRMATION_WEBHOOK_URL: Optional[str] = Field(default=None)
    WEBHOOK_TIMEOUT_SECONDS: int = Field(default=5)
    WEBHOOK_MAX_RETRIES: int = Field(default=3)

    # --- Clinic business rules ---
    CLINIC_NAME: str = Field(default="QuensultingAI Dental Clinic")
    CLINIC_TIMEZONE: str = Field(default="Asia/Kolkata")
    CLINIC_OPEN_HOUR: int = Field(default=9)   # 9 AM
    CLINIC_CLOSE_HOUR: int = Field(default=18)  # 6 PM
    CLINIC_CLOSED_WEEKDAY: int = Field(default=6, description="Python weekday(): Monday=0 ... Sunday=6")
    SLOT_DURATION_MINUTES: int = Field(default=30)

    # --- Local fallback storage if Google Sheets is unreachable ---
    LOCAL_FALLBACK_LOG_PATH: str = Field(default="data/fallback_bookings.csv")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()

VALID_SERVICES = {
    "Dental Cleaning",
    "Root Canal Treatment",
    "Teeth Whitening",
    "Braces Consultation",
    "Tooth Extraction",
    "General Dental Consultation",
}
