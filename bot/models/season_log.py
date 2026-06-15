from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from datetime import datetime

from database.db import Base


class SeasonLog(Base):
    """
    Tugagan mavsum (season) natijasi — arxiv. Har oy mavsum yangilanganda
    foydalanuvchining o'sha oydagi season_xp va o'rni saqlanadi.
    "Oylik hisobot kartasi" (report card) tarixi uchun ham asos bo'ladi.
    """
    __tablename__ = "season_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)

    season_id = Column(String(16), nullable=False)    # "2026-06"
    season_xp = Column(Integer, default=0)
    season_tier = Column(String(40), nullable=True)   # mavsum darajasi nomi
    rank = Column(Integer, nullable=True)             # global o'rin (ixtiyoriy)

    archived_at = Column(DateTime, default=datetime.utcnow)
