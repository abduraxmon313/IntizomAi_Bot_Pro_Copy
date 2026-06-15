from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey
from datetime import datetime

from database.db import Base


class Subtask(Base):
    """
    Rejaning ichki qadamlari (checklist). Bitta Plan'ga bir nechta Subtask.
    Yengil — faqat sarlavha + bajarildi flag + tartib.
    """
    __tablename__ = "subtasks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    plan_id = Column(Integer, ForeignKey("plans.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String(300), nullable=False)
    completed = Column(Boolean, default=False)
    position = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
