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
    # Maqsad turi: FAQAT `yearly` yoki `monthly`.
    # Eski `weekly` va `daily` turlari olib tashlandi — kunlik/haftalik takroriy
    # niyatlar endi Habits'da, bir martalik ishlar esa Plans'da yashaydi.
    # DB'da eski yozuvlar saqlanib qoladi (backward compat) — API tomonida
    # filtrlanadi va foydalanuvchiga ko'rsatilmaydi.
    goal_type = Column(String(20), nullable=False)   # yearly | monthly
    period = Column(String(30), nullable=False)       # 2026 | 2026-05
    completed = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    # Kim yaratgan (audit). NULL = foydalanuvchining o'zi yaratgan.
    created_by_user_id = Column(Integer, nullable=True)

    user = relationship("User", back_populates="goals")
