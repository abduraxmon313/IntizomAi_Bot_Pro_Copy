from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Date
from datetime import datetime

from database.db import Base


class Challenge(Base):
    """
    Murabbiy chaqirig'i (coach challenge) — masalan "7 kun ketma-ket erta turish".

    progress — bajarilgan kunlar/qadamlar soni; target — maqsad.
    status   — active | done | failed.
    """
    __tablename__ = "challenges"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)

    code = Column(String(40), nullable=False)        # "streak_7", "early_5", ...
    title = Column(String(120), nullable=False)
    icon = Column(String(8), default="🎯")

    target = Column(Integer, default=7)
    progress = Column(Integer, default=0)
    reward_xp = Column(Integer, default=50)

    status = Column(String(16), default="active")    # active | done | failed
    last_progress_date = Column(Date, nullable=True)  # bir kunda bir marta sanash uchun

    started_at = Column(DateTime, default=datetime.utcnow)
    ends_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
