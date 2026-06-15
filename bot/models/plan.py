from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Enum, Date, Boolean
from sqlalchemy.orm import relationship
from datetime import datetime
import enum
from database.db import Base
from bot.config import TIMEZONE


def _today_tashkent():
    """Joriy Tashkent sanasi (har chaqirilganda yangidan hisoblanadi)."""
    return datetime.now(TIMEZONE).date()


class PlanStatus(enum.Enum):
    pending = "pending"
    done = "done"
    failed = "failed"


class Plan(Base):
    __tablename__ = "plans"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    title = Column(String(500), nullable=False)
    description = Column(String(1000), nullable=True)
    scheduled_time = Column(String(10), nullable=True)   # "06:00" formatda
    plan_date = Column(Date, default=_today_tashkent)
    status = Column(Enum(PlanStatus), default=PlanStatus.pending)
    score_value = Column(Integer, default=5)
    created_at = Column(DateTime, default=datetime.utcnow)
    notified_at = Column(DateTime, nullable=True)

    # ── Faza 2: kategoriya / teglar / izoh ──────────────────────
    category = Column(String(40), nullable=True)         # "sport" | "oqish" | ...
    tags = Column(String(255), nullable=True)            # vergul bilan ajratilgan
    notes = Column(String(2000), nullable=True)

    # ── Faza 2: takrorlanuvchi reja (recurring) ─────────────────
    recurrence = Column(String(20), default="none")      # none|daily|weekdays|weekly
    recurrence_days = Column(String(20), nullable=True)  # "0,2,4" (Du=0)
    recurrence_parent_id = Column(Integer, nullable=True)
    is_template = Column(Boolean, default=False)         # ko'rinmas shablon

    # ── Faza 3: smart reminder ──────────────────────────────────
    snoozed_count = Column(Integer, default=0)

    user = relationship("User", back_populates="plans")
    score_logs = relationship("ScoreLog", back_populates="plan", cascade="all, delete")