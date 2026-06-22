from sqlalchemy import Column, Integer, String, Date, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime
from database.db import Base


class DailyCheckin(Base):
    """Kunlik kayfiyat + energiya (daily loop anchor). Mood/energy faqat."""
    __tablename__ = "daily_checkins"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    checkin_date = Column(Date, nullable=False)

    mood = Column(String(20), nullable=True)      # 🔥 / 💪 / 😐 / 😴 / 😞
    energy = Column(Integer, nullable=True)        # 1..5

    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="checkins")
