import asyncio
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


# Jadvallar tayyorligini bir martalik qilish uchun (ko'p bot bitta jarayonda).
_tables_ready = False
_tables_lock = asyncio.Lock()


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
    ("referred_by", "BIGINT"),
    ("referral_count", "INTEGER DEFAULT 0"),
    ("referral_rewards_given", "INTEGER DEFAULT 0"),
]

# payment_orders jadvali uchun yangi ustunlar.
PAYMENT_ORDER_NEW_COLUMNS = [
    ("pay_message_id", "BIGINT"),
]

# plans jadvali uchun yangi ustunlar (Faza 2: recurring, tags, notes; Faza 3: snooze).
PLAN_NEW_COLUMNS = [
    ("category", "VARCHAR(40)"),
    ("tags", "VARCHAR(255)"),
    ("notes", "VARCHAR(2000)"),
    ("recurrence", "VARCHAR(20) DEFAULT 'none'"),   # none|daily|weekdays|weekly
    ("recurrence_days", "VARCHAR(20)"),             # "0,2,4" (Mon=0)
    ("recurrence_parent_id", "INTEGER"),            # qaysi template'dan yaratilgan
    ("is_template", "BOOLEAN DEFAULT FALSE"),       # takrorlanuvchi shablon (ko'rinmas)
    ("snoozed_count", "INTEGER DEFAULT 0"),         # smart reminder snooze soni
]

# goals jadvali uchun yangi ustunlar (Faza 2: tags, notes).
GOAL_NEW_COLUMNS = [
    ("category", "VARCHAR(40)"),
    ("tags", "VARCHAR(255)"),
    ("notes", "VARCHAR(2000)"),
]

# daily_checkins jadvali uchun yangi ustunlar (Faza 3: kechki refleksiya rituali).
CHECKIN_NEW_COLUMNS = [
    ("reflection", "VARCHAR(2000)"),    # kechki refleksiya matni
    ("win_of_day", "VARCHAR(500)"),     # kunning eng yaxshi yutug'i
    ("gratitude", "VARCHAR(500)"),      # minnatdorchilik
]

# users jadvali uchun yangi ustunlar (Faza 3: seasons; Faza 4: guruh).
USER_EXTRA_COLUMNS = [
    ("season_id", "VARCHAR(16)"),               # "2026-06"
    ("season_xp", "INTEGER DEFAULT 0"),
    ("group_id", "INTEGER"),                    # joriy study-group id
    ("ai_credits", "INTEGER DEFAULT 0"),        # premium oylik AI kreditlari (bonus)
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
    "CREATE INDEX IF NOT EXISTS ix_analytics_tid_date ON analytics_events (telegram_id, event_date)",
    "CREATE INDEX IF NOT EXISTS ix_analytics_event_date2 ON analytics_events (event, event_date)",
    "CREATE INDEX IF NOT EXISTS ix_subtasks_plan ON subtasks (plan_id)",
    "CREATE INDEX IF NOT EXISTS ix_challenges_user ON challenges (user_id, status)",
    "CREATE INDEX IF NOT EXISTS ix_group_members_group ON group_members (group_id)",
    "CREATE INDEX IF NOT EXISTS ix_group_members_tid ON group_members (telegram_id)",
    "CREATE INDEX IF NOT EXISTS ix_plans_template ON plans (is_template, recurrence)",
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

    # Faza 2/3/4 — yangi ustunlar (idempotent). Jadval -> ustunlar ro'yxati.
    _extra_table_columns = [
        ("plans", PLAN_NEW_COLUMNS),
        ("goals", GOAL_NEW_COLUMNS),
        ("daily_checkins", CHECKIN_NEW_COLUMNS),
        ("users", USER_EXTRA_COLUMNS),
    ]
    for table, cols in _extra_table_columns:
        for col, ddl in cols:
            try:
                await conn.execute(
                    text(f'ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col} {ddl}')
                )
            except Exception as e:
                logger.warning(f"Migration skip {table}.{col}: {e}")

    # Ko'lamlilik (scalability) uchun indekslar — userlar/rejalar ko'payganda
    # so'rovlar full-scan qilmasligi uchun. CREATE INDEX IF NOT EXISTS idempotent
    # (mavjud bo'lsa qayta yaratmaydi), shuning uchun har startda xavfsiz ishlaydi.
    for ddl in NEW_INDEXES:
        try:
            await conn.execute(text(ddl))
        except Exception as e:
            logger.warning(f"Index skip: {e}")


async def create_tables():
    # Bir necha bot (asosiy + Dilshodbek) bitta jarayonda ishlaganda, bu funksiya
    # bir nechta task'dan chaqirilishi mumkin. Lock + flag bilan jadval yaratish
    # va migratsiyalar FAQAT BIR MARTA, ketma-ket bajarilishini kafolatlaymiz
    # (bir vaqtda ikkita DDL → "already exists" xatosi bo'lmasligi uchun).
    global _tables_ready
    async with _tables_lock:
        if _tables_ready:
            return
        async with engine.begin() as conn:
            from bot.models import (  # noqa
                user, plan, score_log, admin, goal, achievement, checkin,
                subscription, payment_order, referral, analytics_event,
                subtask, challenge, season_log, study_group,
            )
            await conn.run_sync(Base.metadata.create_all)
            await _run_migrations(conn)
        _tables_ready = True
