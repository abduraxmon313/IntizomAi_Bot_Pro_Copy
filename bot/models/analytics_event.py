from sqlalchemy import Column, Integer, BigInteger, String, DateTime, Index
from datetime import datetime

from database.db import Base


class AnalyticsEvent(Base):
    """
    Mahsulot tahlili (product analytics) — har bir muhim foydalanuvchi harakati
    shu jadvalga yoziladi. Bu retention (D1/D7/D30), activation va funnel
    metrikalarini hisoblash uchun yagona manba.

    Eslatma: yozish HAR DOIM "best-effort" (xato bo'lsa yutiladi) — analitika
    asosiy oqimni (reja qo'shish, AI, to'lov) HECH QACHON to'xtatmasligi kerak.
    """
    __tablename__ = "analytics_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    # users.id (bo'lsa) — JOIN uchun. Anonim hodisalarda None bo'lishi mumkin.
    user_id = Column(Integer, nullable=True, index=True)
    telegram_id = Column(BigInteger, nullable=True, index=True)

    # Hodisa nomi: signup | open | first_plan | plan_created | plan_completed |
    #              first_win | ai_chat | paywall_view | subscribe_start |
    #              subscribe_success | ritual_morning | ritual_evening |
    #              group_create | group_join | challenge_start | ...
    event = Column(String(48), nullable=False, index=True)

    # Qo'shimcha kontekst (JSON-string, ixtiyoriy). Masalan {"plan":"1m"}.
    props = Column(String(500), nullable=True)

    # Tashkent sanasi (YYYY-MM-DD) — kunlik DAU/retention so'rovlarini
    # timezone bilan ovora bo'lmasdan tez hisoblash uchun denormalizatsiya.
    event_date = Column(String(10), nullable=True, index=True)

    created_at = Column(DateTime, default=datetime.utcnow)


Index("ix_analytics_event_date", AnalyticsEvent.event, AnalyticsEvent.event_date)
