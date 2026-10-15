from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.security import APIKeyHeader

from app.core.config import settings
from app.core.database import get_db
from app.models.clinical import Role, User, UserRole
from sqlalchemy.orm import Session

CONFIGURED_API_KEY = settings.API_KEY

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

async def get_api_key(api_key: str = Depends(api_key_header)):
    """
    Dependency to verify the API key.
    """
    if not CONFIGURED_API_KEY:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="API credential validation is not configured.")
    if api_key != CONFIGURED_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API Key. Please provide a valid X-API-Key header."
        )
    return api_key


def require_clinician_roles(*allowed_roles: str):
    async def clinician_dependency(
        request: Request,
        clinician_id: int | None = Header(default=None, alias="X-Clinician-ID"),
        db: Session = Depends(get_db),
        _api_key: str = Depends(get_api_key),
    ) -> User:
        if clinician_id is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authenticated clinician identity is required.",
            )
        clinician = db.query(User).filter(User.id == clinician_id, User.is_active.is_(True)).first()
        if clinician is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Clinician not found or inactive.")

        assigned_roles = {
            role_name
            for (role_name,) in (
                db.query(Role.name)
                .join(UserRole, UserRole.role_id == Role.id)
                .filter(UserRole.user_id == clinician.id, Role.is_active.is_(True))
                .all()
            )
        }
        if not assigned_roles.intersection(allowed_roles):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Clinician role is not permitted for this action.")
        request.state.authenticated_clinician_id = clinician.id
        return clinician

    return clinician_dependency
