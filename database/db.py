import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

from bot.config import DATABASE_URL


logger = logging.getLogger(__name__)


engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    pool_pre_ping=True,
    pool_recycle=1800,
    pool_size=10,
    max_overflow=20,
    pool_timeout=30,
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False
)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        yield session


# ─────────────────────────────────────────────────────────────
#  Lightweight idempotent migrations for new gamification columns.
#  Postgres (Railway) — uses ADD COLUMN IF NOT EXISTS.
# ─────────────────────────────────────────────────────────────
USER_NEW_COLUMNS = [
    ("xp", "INTEGER DEFAULT 0"),
    ("level", "INTEGER DEFAULT 1"),
    ("longest_streak", "INTEGER DEFAULT 0"),
    ("last_completed_date", "DATE"),
    ("streak_freezes", "INTEGER DEFAULT 0"),
    ("discipline_score", "INTEGER DEFAULT 50"),
    ("weekly_xp", "INTEGER DEFAULT 0"),
    ("perfect_days", "INTEGER DEFAULT 0"),
    ("is_premium", "BOOLEAN DEFAULT FALSE"),
    ("premium_until", "TIMESTAMP"),
    ("onboarded", "BOOLEAN DEFAULT FALSE"),
    ("rank_title", "VARCHAR(40)"),
    ("avatar_emoji", "VARCHAR(8) DEFAULT '🌱'"),
    ("ai_msgs_date", "DATE"),
    ("ai_msgs_count", "INTEGER DEFAULT 0"),
]

# payment_orders jadvali uchun yangi ustunlar.
PAYMENT_ORDER_NEW_COLUMNS = [
    ("pay_message_id", "BIGINT"),
]

# Hot so'rovlar uchun indekslar (Postgres). Foreign-key ustunlar Postgres'da
# avtomatik indekslanmaydi — shuning uchun qo'lda qo'shamiz.
NEW_INDEXES = [
    "CREATE INDEX IF NOT EXISTS ix_plans_user_id ON plans (user_id)",
    "CREATE INDEX IF NOT EXISTS ix_plans_user_date ON plans (user_id, plan_date)",
    "CREATE INDEX IF NOT EXISTS ix_plans_due ON plans (scheduled_time, status, plan_date)",
    "CREATE INDEX IF NOT EXISTS ix_plans_status_date ON plans (status, plan_date)",
    "CREATE INDEX IF NOT EXISTS ix_score_logs_user_created ON score_logs (user_id, created_at)",
    "CREATE INDEX IF NOT EXISTS ix_goals_user_id ON goals (user_id)",
    "CREATE INDEX IF NOT EXISTS ix_achievements_user_id ON achievements (user_id)",
    "CREATE INDEX IF NOT EXISTS ix_checkins_user_date ON daily_checkins (user_id, checkin_date)",
    "CREATE INDEX IF NOT EXISTS ix_subscriptions_user_active ON subscriptions (user_id, is_active)",
    "CREATE INDEX IF NOT EXISTS ix_users_premium_until ON users (premium_until)",
    "CREATE INDEX IF NOT EXISTS ix_users_last_active ON users (last_active)",
    "CREATE INDEX IF NOT EXISTS ix_users_is_active ON users (is_active)",
]


async def _run_migrations(conn):
    for col, ddl in USER_NEW_COLUMNS:
        try:
            await conn.execute(
                text(f'ALTER TABLE users ADD COLUMN IF NOT EXISTS {col} {ddl}')
            )
        except Exception as e:
            logger.warning(f"Migration skip {col}: {e}")

    # payment_orders uchun yangi ustunlar (idempotent — ADD COLUMN IF NOT EXISTS).
    for col, ddl in PAYMENT_ORDER_NEW_COLUMNS:
        try:
            await conn.execute(
                text(f'ALTER TABLE payment_orders ADD COLUMN IF NOT EXISTS {col} {ddl}')
            )
        except Exception as e:
            logger.warning(f"Migration skip payment_orders.{col}: {e}")

    # Ko'lamlilik (scalability) uchun indekslar — userlar/rejalar ko'payganda
    # so'rovlar full-scan qilmasligi uchun. CREATE INDEX IF NOT EXISTS idempotent
    # (mavjud bo'lsa qayta yaratmaydi), shuning uchun har startda xavfsiz ishlaydi.
    for ddl in NEW_INDEXES:
        try:
            await conn.execute(text(ddl))
        except Exception as e:
            logger.warning(f"Index skip: {e}")


async def create_tables():
    async with engine.begin() as conn:
        from bot.models import (  # noqa
            user, plan, score_log, admin, goal, achievement, checkin,
            subscription, payment_order,
        )
        await conn.run_sync(Base.metadata.create_all)
        await _run_migrations(conn)
