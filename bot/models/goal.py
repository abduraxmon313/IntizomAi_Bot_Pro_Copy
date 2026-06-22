from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime
from database.db import Base


class Goal(Base):
    __tablename__ = "goals"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    title = Column(String(500), nullable=False)
    description = Column(String(1000), nullable=True)
    goal_type = Column(String(20), nullable=False)   # yearly | monthly | weekly | daily
    period = Column(String(30), nullable=False)       # 2026 | 2026-05 | 2026-W21 | 2026-05-22
    completed = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="goals")
