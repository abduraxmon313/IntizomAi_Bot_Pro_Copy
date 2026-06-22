from sqlalchemy import Column, Integer, BigInteger, String, DateTime, Index
from datetime import datetime
from database.db import Base


class AnalyticsEvent(Base):
    """
    Yengil analitika hodisalari — funnel/retention o'lchovi uchun.

    Misol event'lar: signup, start, plan_created, habit_created, goal_created,
    ai_chat, paywall_view, miniapp_open, checkout_started, premium_activated,
    trial_granted, onboarding_done.
    """
    __tablename__ = "analytics_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    telegram_id = Column(BigInteger, nullable=True)
    user_id = Column(Integer, nullable=True)
    event = Column(String(50), nullable=False)
    props = Column(String(300), nullable=True)   # ixtiyoriy qo'shimcha (manba, plan, ...)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_analytics_event_created", "event", "created_at"),
        Index("ix_analytics_created", "created_at"),
    )
