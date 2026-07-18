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
    ("display_name", "VARCHAR(255)"),
    ("notifications_enabled", "BOOLEAN DEFAULT TRUE"),
    ("trial_used", "BOOLEAN DEFAULT FALSE"),
    ("photo_url", "VARCHAR(512)"),
]

# habits jadvali uchun yangi ustunlar (avvalgi versiyada yaratilgan bo'lsa).
HABIT_NEW_COLUMNS = [
    ("frequency", "VARCHAR(12) DEFAULT 'daily'"),
    ("weekdays", "VARCHAR(20)"),
    ("duration_type", "VARCHAR(12) DEFAULT 'permanent'"),
    ("target_days", "INTEGER"),
    ("start_date", "DATE"),
    ("sort_order", "INTEGER DEFAULT 0"),
    ("archived", "BOOLEAN DEFAULT FALSE"),
    ("reminder_time", "VARCHAR(5)"),
]

# payment_orders jadvali uchun yangi ustunlar.
PAYMENT_ORDER_NEW_COLUMNS = [
    ("pay_message_id", "BIGINT"),
]

# promocodes jadvali uchun yangi ustunlar.
PROMOCODE_NEW_COLUMNS = [
    ("is_free", "BOOLEAN DEFAULT FALSE"),
]

# plans/goals/habits jadvallarida "kim yaratgan" audit ustuni (Do'stlar moduli).
CREATED_BY_TABLES = ("plans", "goals", "habits")

# group_permissions jadvali uchun yangi ustunlar (Do'stlar visibility).
GROUP_PERMISSIONS_NEW_COLUMNS = [
    ("can_view", "BOOLEAN DEFAULT FALSE NOT NULL"),
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
    "CREATE INDEX IF NOT EXISTS ix_habits_user_id ON habits (user_id)",
    "CREATE INDEX IF NOT EXISTS ix_habit_logs_habit_date ON habit_logs (habit_id, log_date)",
    "CREATE INDEX IF NOT EXISTS ix_habit_logs_user_date ON habit_logs (user_id, log_date)",
    # Do'stlar (guruhlar) moduli
    "CREATE INDEX IF NOT EXISTS ix_group_members_user ON group_members (user_id)",
    "CREATE INDEX IF NOT EXISTS ix_group_members_group ON group_members (group_id)",
    "CREATE INDEX IF NOT EXISTS ix_group_permissions_group ON group_permissions (group_id)",
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

    # promocodes uchun yangi ustunlar (is_free — `+`/`-` turi).
    for col, ddl in PROMOCODE_NEW_COLUMNS:
        try:
            await conn.execute(
                text(f'ALTER TABLE promocodes ADD COLUMN IF NOT EXISTS {col} {ddl}')
            )
        except Exception as e:
            logger.warning(f"Migration skip promocodes.{col}: {e}")

    # plans/goals/habits: created_by_user_id — Do'stlar guruhida boshqa a'zo
    # yaratgan bo'lsa uning users.id si. NULL = foydalanuvchining o'zi yaratgan.
    for tbl in CREATED_BY_TABLES:
        try:
            await conn.execute(
                text(f'ALTER TABLE {tbl} ADD COLUMN IF NOT EXISTS created_by_user_id INTEGER')
            )
        except Exception as e:
            logger.warning(f"Migration skip {tbl}.created_by_user_id: {e}")

    # group_permissions: can_view — Do'stlar guruhida "kim mening reja/odat/
    # maqsadlarimni ko'ra oladi" toggle. Mavjud rowlar can_view=FALSE bilan
    # keladi; can_manage=TRUE bo'lganlar effective_visible = True (OR).
    for col, ddl in GROUP_PERMISSIONS_NEW_COLUMNS:
        try:
            await conn.execute(
                text(f'ALTER TABLE group_permissions ADD COLUMN IF NOT EXISTS {col} {ddl}')
            )
        except Exception as e:
            logger.warning(f"Migration skip group_permissions.{col}: {e}")

    # habits uchun yangi ustunlar (frequency/weekdays/duration/start_date...).
    # Jadval shu transaksiyada create_all bilan yaratilgani uchun yangi DB'da
    # ustunlar allaqachon mavjud (no-op); eski DB'da esa qo'shiladi.
    for col, ddl in HABIT_NEW_COLUMNS:
        try:
            await conn.execute(
                text(f'ALTER TABLE habits ADD COLUMN IF NOT EXISTS {col} {ddl}')
            )
        except Exception as e:
            logger.warning(f"Migration skip habits.{col}: {e}")

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
                subscription, payment_order, referral, habit, group,
                plan_override,
            )
            await conn.run_sync(Base.metadata.create_all)
            await _run_migrations(conn)
        _tables_ready = True
