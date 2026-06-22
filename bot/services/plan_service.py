from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from bot.models.plan import Plan, PlanStatus
from bot.models.user import User
from datetime import date, timedelta, datetime
from bot.config import TIMEZONE


def plan_block_reason(plan_date, scheduled_time):
    """
    Rejani 'bajarildi' deb belgilashga to'siq bormi?
      • None     -> belgilash mumkin
      • 'past'   -> kechagi yoki undan oldingi kun (belgilab bo'lmaydi)
      • 'future' -> kelajak kun yoki bugun vaqti hali kelmagan (vaqti kelmagan)
    """
    now = datetime.now(TIMEZONE)
    today = now.date()
    if plan_date is None:
        return None  # sanasi yo'q -> bugun deb hisoblaymiz, ruxsat
    if plan_date < today:
        return "past"
    if plan_date > today:
        return "future"
    # plan_date == bugun
    if not scheduled_time:
        return None
    try:
        parts = str(scheduled_time).split(":")
        hh = int(parts[0])
        mm = int(parts[1]) if len(parts) > 1 else 0
        due = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        return None if now >= due else "future"
    except Exception:
        return None


def plan_is_due(plan_date, scheduled_time) -> bool:
    """Reja 'bajarildi' deb belgilanishi mumkinmi (hech qanday to'siq yo'qmi)?"""
    return plan_block_reason(plan_date, scheduled_time) is None



async def create_plans(session: AsyncSession, user: User, plans_data: list[dict]) -> list[Plan]:
    """GPT dan kelgan plan listni DBga saqlaydi"""
    plans = []
    today = datetime.now(TIMEZONE).date()
    
    for p in plans_data:
        # Agar ertaga uchun bo'lsa
        plan_date = today + timedelta(days=1) if p.get("for_tomorrow") else today
        
        plan = Plan(
            user_id=user.id,
            title=p["title"],
            description=p.get("description"),
            scheduled_time=p.get("scheduled_time"),
            plan_date=plan_date,
            score_value=p.get("score_value", 5),
        )
        session.add(plan)
        plans.append(plan)
    
    await session.commit()
    for plan in plans:
        await session.refresh(plan)
    return plans


async def get_today_plans(session: AsyncSession, user: User) -> list[Plan]:
    """Bugungi barcha rejalarni qaytaradi"""
    today = datetime.now(TIMEZONE).date()
    
    result = await session.execute(
        select(Plan).where(
            and_(
                Plan.user_id == user.id,
                Plan.plan_date == today
            )
        ).order_by(Plan.scheduled_time)
    )
    return result.scalars().all()


async def get_plan_by_id(session: AsyncSession, plan_id: int) -> Plan | None:
    result = await session.execute(select(Plan).where(Plan.id == plan_id))
    return result.scalar_one_or_none()


async def update_plan_status(session: AsyncSession, plan: Plan, status: PlanStatus):
    plan.status = status
    await session.commit()


async def delete_plan(session: AsyncSession, plan: Plan):
    await session.delete(plan)
    await session.commit()


async def create_plan_single(
    session: AsyncSession,
    user: User,
    title: str,
    description: str | None,
    scheduled_time: str | None,
    plan_date_str: str | None,
    score_value: int = 5,
) -> Plan:
    if plan_date_str:
        try:
            pd = date.fromisoformat(plan_date_str)
        except Exception:
            pd = datetime.now(TIMEZONE).date()
    else:
        pd = datetime.now(TIMEZONE).date()
    plan = Plan(
        user_id=user.id,
        title=title,
        description=description,
        scheduled_time=scheduled_time,
        plan_date=pd,
        score_value=score_value,
    )
    session.add(plan)
    await session.commit()
    await session.refresh(plan)
    return plan


async def update_plan_fields(
    session: AsyncSession,
    plan_id: int,
    user_id: int,
    title: str | None = None,
    description: str | None = None,
    scheduled_time: str | None = None,
    status: str | None = None,
) -> Plan | None:
    result = await session.execute(
        select(Plan).where(and_(Plan.id == plan_id, Plan.user_id == user_id))
    )
    plan = result.scalar_one_or_none()
    if not plan:
        return None
    if title is not None:
        plan.title = title
    if description is not None:
        plan.description = description
    if scheduled_time is not None:
        plan.scheduled_time = scheduled_time
    if status is not None:
        try:
            plan.status = PlanStatus(status)
        except Exception:
            pass
    await session.commit()
    await session.refresh(plan)
    return plan


async def delete_plan_by_id(session: AsyncSession, plan_id: int, user_id: int) -> bool:
    result = await session.execute(
        select(Plan).where(and_(Plan.id == plan_id, Plan.user_id == user_id))
    )
    plan = result.scalar_one_or_none()
    if not plan:
        return False
    await session.delete(plan)
    await session.commit()
    return True


async def get_plans_in_range(
    session: AsyncSession, user: User, date_from: str, date_to: str
) -> list[Plan]:
    try:
        df = date.fromisoformat(date_from)
        dt = date.fromisoformat(date_to)
    except Exception:
        return []
    result = await session.execute(
        select(Plan).where(
            and_(
                Plan.user_id == user.id,
                Plan.plan_date >= df,
                Plan.plan_date <= dt,
            )
        ).order_by(Plan.plan_date, Plan.scheduled_time)
    )
    return result.scalars().all()


async def get_pending_plans_to_notify(session: AsyncSession) -> list[Plan]:
    """Vaqti kelgan va hali notification yuborilmagan rejalarni qaytaradi"""
    now_tashkent = datetime.now(TIMEZONE)
    now_time = now_tashkent.strftime("%H:%M")
    today = now_tashkent.date()
    
    result = await session.execute(
        select(Plan).where(
            and_(
                Plan.scheduled_time == now_time,
                Plan.status == PlanStatus.pending,
                Plan.notified_at == None,
                Plan.plan_date == today
            )
        )
    )
    return result.scalars().all()


async def get_all_pending_plans_today(session: AsyncSession) -> list[Plan]:
    """Bugungi barcha pending rejalarni qaytaradi"""
    today = datetime.now(TIMEZONE).date()
    
    result = await session.execute(
        select(Plan).where(
            and_(
                Plan.status == PlanStatus.pending,
                Plan.plan_date == today
            )
        )
    )
    return result.scalars().all()


async def move_plan_to_tomorrow(session: AsyncSession, plan: Plan) -> Plan:
    """Rejani keyingi kunga ko'chiradi"""
    tomorrow = datetime.now(TIMEZONE).date() + timedelta(days=1)
    
    new_plan = Plan(
        user_id=plan.user_id,
        title=plan.title,
        description=plan.description,
        scheduled_time=plan.scheduled_time,
        plan_date=tomorrow,
        score_value=plan.score_value,
        status=PlanStatus.pending,
    )
    session.add(new_plan)
    
    plan.status = PlanStatus.failed
    await session.commit()
    await session.refresh(new_plan)
    return new_plan


async def duplicate_plan_for_tomorrow(session: AsyncSession, plan: Plan) -> Plan:
    """Rejani ertaga uchun nusxalaydi (continue feature)"""
    tomorrow = datetime.now(TIMEZONE).date() + timedelta(days=1)
    
    new_plan = Plan(
        user_id=plan.user_id,
        title=plan.title,
        description=plan.description,
        scheduled_time=plan.scheduled_time,
        plan_date=tomorrow,
        score_value=plan.score_value,
        status=PlanStatus.pending,
    )
    session.add(new_plan)
    await session.commit()
    await session.refresh(new_plan)
    return new_plan
