import json
import logging

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.database import SessionLocal
from app.models.audit import AuditLog

logger = logging.getLogger(__name__)


class AuditMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)

        # Log mutating requests and requests to patient-related endpoints.
        if request.method in {"POST", "PUT", "DELETE"} or "patients" in request.url.path:
            db = SessionLocal()
            try:
                log_entry = AuditLog(
                    user_id=str(getattr(request.state, "authenticated_clinician_id", "anonymous")),
                    action=f"{request.method} {request.url.path}",
                    resource_type="API_ENDPOINT",
                    resource_id=request.url.path,
                    details=json.dumps({
                        "status_code": response.status_code,
                    }),
                    ip_address=request.client.host if request.client else "unknown",
                )
                db.add(log_entry)
                db.commit()
            except Exception:
                db.rollback()
                logger.exception("Audit log write failed")
            finally:
                db.close()

        return response
