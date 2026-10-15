from sqlalchemy import Column, DateTime, Integer, String, Text
from sqlalchemy.sql import func

from app.core.database import Base


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime(timezone=True), server_default=func.now())
    user_id = Column(String, index=True)  # Replace with authenticated user ID when available.
    action = Column(String, index=True)
    resource_type = Column(String)
    resource_id = Column(String)
    details = Column(Text)
    ip_address = Column(String)
