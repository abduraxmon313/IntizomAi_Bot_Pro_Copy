from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from bot.models.user import User
from datetime import datetime


async def get_or_create_user(session: AsyncSession, telegram_id: int, full_name: str, username: str,
                             bot_name: str | None = None) -> User:
    result = await session.execute(select(User).where(User.telegram_id == telegram_id))
    user = result.scalar_one_or_none()

    if not user:
        user = User(
            telegram_id=telegram_id,
            full_name=full_name,
            username=username,
            started_main_bot=(bot_name == "main"),
            started_dilshodbek_bot=(bot_name == "dilshodbek"),
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user

    # Mavjud foydalanuvchi — ism/username o'zgargan bo'lsa yangilaymiz
    changed = False
    if full_name and user.full_name != full_name:
        user.full_name = full_name
        changed = True
    if username is not None and user.username != username:
        user.username = username
        changed = True
    # Bot bayrog'ini yoqamiz (faqat True ga o'tkazamiz, hech qachon False qilmaymiz)
    if bot_name == "main" and not user.started_main_bot:
        user.started_main_bot = True
        changed = True
    elif bot_name == "dilshodbek" and not user.started_dilshodbek_bot:
        user.started_dilshodbek_bot = True
        changed = True
    user.last_active = datetime.utcnow()
    try:
        await session.commit()
        if changed:
            await session.refresh(user)
    except Exception:
        await session.rollback()

    return user


async def get_user_by_telegram_id(session: AsyncSession, telegram_id: int) -> User | None:
    result = await session.execute(select(User).where(User.telegram_id == telegram_id))
    return result.scalar_one_or_none()


async def update_user_score(session: AsyncSession, user: User, score_change: int):
    user.total_score += score_change
    user.last_active = datetime.utcnow()
    await session.commit()


async def update_streak(session: AsyncSession, user: User, increment: bool = True):
    if increment:
        user.streak += 1
    else:
        user.streak = 0
    await session.commit()