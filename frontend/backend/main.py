import logging
import os
from urllib.parse import urlsplit

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.core.config import settings
from app.core.database import engine
from app.core.audit_middleware import AuditMiddleware
from app.api import routes
from app.models import models  # noqa: F401 - register models with SQLAlchemy metadata

if settings.is_hosted and not settings.API_KEY.strip():
    raise RuntimeError("API_KEY must be explicitly configured in hosted environments.")


def get_cors_origins() -> list[str]:
    configured_origins = settings.CORS_ORIGINS.strip()
    if settings.is_hosted and not os.getenv("CORS_ORIGINS", "").strip():
        raise RuntimeError("CORS_ORIGINS must explicitly include the hosted frontend origin.")
    if not configured_origins:
        configured_origins = "http://localhost:5173,http://localhost:3000"
    origins = []
    for configured_origin in configured_origins.split(","):
        origin = configured_origin.strip().rstrip("/")
        if not origin:
            continue
        parsed = urlsplit(origin)
        if (
            "*" in origin
            or parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.username
            or parsed.password
            or parsed.path
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("CORS_ORIGINS must contain explicit HTTP(S) origins without paths or wildcards.")
        origins.append(origin)
    if not origins:
        raise ValueError("CORS_ORIGINS must contain at least one explicit origin.")
    return origins


app = FastAPI(
    title=settings.APP_NAME,
    description=settings.DESCRIPTION,
    version=settings.VERSION,
)
app.add_middleware(AuditMiddleware)

# CORS setup
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API routes
app.include_router(routes.router, prefix="/api/v1", tags=["MediSafe APIs"])


@app.get("/")
def read_root():
    return {"message": f"Welcome to {settings.APP_NAME}", "docs": "/docs"}


@app.get("/api/health")
def health_check():
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception:
        logging.getLogger(__name__).warning("Database health check failed")
        return JSONResponse(
            status_code=503,
            content={"status": "unhealthy", "database": "disconnected"},
        )
    return {"status": "healthy", "database": "connected"}