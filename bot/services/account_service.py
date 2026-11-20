"""
Hisobni butunlay o'chirish (App Store 5.1.1(v) / Google Play talabi).

Foydalanuvchi va unga tegishli barcha ma'lumotlar BITTA tranzaksiyada
o'chiriladi. Bola jadvallar aniq tartibda o'chiriladi — production bazadagi
eski FK cheklovlarida ON DELETE CASCADE bo'lmasligi mumkin (create_all mavjud
jadvallarni o'zgartirmaydi), shuning uchun kaskadga tayanmaymiz.

Saqlanib qoladigan yagona narsa — `referrals` jadvali (faqat telegram_id
juftliklari, shaxsiy ma'lumotsiz). U bitta Telegram akkauntini hisobni
o'chirib-qayta ochish orqali taklif mukofotlarini qayta-qayta olishdan
himoya qiladi (maxfiylik siyosatida ko'rsatilgan).
"""
import logging

from sqlalchemy import delete, select, update, or_
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models import (
    Achievement, Admin, AppLoginRequest, BotChat, DailyCheckin, Goal, Group,
    GroupMember, GroupPermission, Habit, HabitLog, PaymentOrder, Plan,
    ScoreLog, Subscription, User,
)

logger = logging.getLogger(__name__)


class AccountDeletionForbidden(Exception):
    """Bu hisobni ilova orqali o'chirib bo'lmaydi (masalan, admin)."""


async def delete_account(session: AsyncSession, user: User) -> None:
    uid, tid = user.id, user.telegram_id

    if await session.scalar(select(Admin.id).where(Admin.telegram_id == tid)):
        raise AccountDeletionForbidden(
            "Admin hisobini ilova orqali o'chirib bo'lmaydi."
        )

    owned_groups = select(Group.id).where(Group.owner_user_id == uid).scalar_subquery()
    user_plans = select(Plan.id).where(Plan.user_id == uid).scalar_subquery()
    user_habits = select(Habit.id).where(Habit.user_id == uid).scalar_subquery()

    try:
        # Odatlar va rejalar (va ularga bog'liq loglar)
        await session.execute(delete(HabitLog).where(
            or_(HabitLog.user_id == uid, HabitLog.habit_id.in_(user_habits))
        ))
        await session.execute(delete(Habit).where(Habit.user_id == uid))
        await session.execute(delete(ScoreLog).where(
            or_(ScoreLog.user_id == uid, ScoreLog.plan_id.in_(user_plans))
        ))
        await session.execute(delete(Plan).where(Plan.user_id == uid))
        await session.execute(delete(Goal).where(Goal.user_id == uid))
        await session.execute(delete(Achievement).where(Achievement.user_id == uid))
        await session.execute(delete(DailyCheckin).where(DailyCheckin.user_id == uid))

        # Guruhlar: o'zi ega bo'lganlari (a'zolari va ruxsatlari bilan) va
        # boshqa guruhlardagi a'zolik/ruxsatlari.
        await session.execute(delete(GroupPermission).where(or_(
            GroupPermission.grantor_user_id == uid,
            GroupPermission.grantee_user_id == uid,
            GroupPermission.group_id.in_(owned_groups),
        )))
        await session.execute(delete(GroupMember).where(or_(
            GroupMember.user_id == uid,
            GroupMember.group_id.in_(owned_groups),
        )))
        await session.execute(delete(Group).where(Group.owner_user_id == uid))

        # To'lov va obuna yozuvlari
        await session.execute(delete(Subscription).where(Subscription.user_id == uid))
        await session.execute(delete(PaymentOrder).where(PaymentOrder.user_id == uid))

        # telegram_id bo'yicha bog'langan yozuvlar
        await session.execute(delete(AppLoginRequest).where(AppLoginRequest.telegram_id == tid))
        await session.execute(delete(BotChat).where(
            BotChat.chat_id == tid, BotChat.chat_type == "private",
        ))
        await session.execute(update(BotChat).where(BotChat.added_by == tid).values(added_by=None))

        # Boshqalarning yozuvlaridagi "kim yaratgan" havolalari
        for model in (Plan, Goal, Habit):
            await session.execute(
                update(model).where(model.created_by_user_id == uid).values(created_by_user_id=None)
            )

        await session.execute(delete(User).where(User.id == uid))
        await session.commit()
    except Exception:
        await session.rollback()
        logger.exception("Hisobni o'chirishda xato (user_id=%s)", uid)
        raise

    # Xotiradagi avatar keshidan ham olib tashlaymiz.
    try:
        from webapp.routes import avatar
        avatar._CACHE.pop(tid, None)
    except Exception:
        pass

    logger.info("Hisob o'chirildi: user_id=%s", uid)
