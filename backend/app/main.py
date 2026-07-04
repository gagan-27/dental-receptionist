import logging
import sys

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError

from app.config import settings
from app.models import HealthResponse
from app.routers import retell_functions

logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
    stream=sys.stdout,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("main")

app = FastAPI(
    title="QuensultingAI Dental Clinic — Voice Agent Automation Backend",
    description="Webhook endpoints consumed by RetellAI custom function nodes.",
    version="1.0.0",
)

app.include_router(retell_functions.router)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    logger.warning("Validation error on %s: %s", request.url.path, exc)
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"detail": exc.errors()},
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.error("Unhandled exception on %s: %s", request.url.path, exc, exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Internal server error. This has been logged."},
    )


@app.get("/health", response_model=HealthResponse)
async def health():
    return HealthResponse(status="ok", app_env=settings.APP_ENV)


@app.get("/")
async def root():
    return {"service": "quensultingai-dental-voice-agent-backend", "docs": "/docs"}
