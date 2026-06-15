"""
Subtasklar (checklist) va izohlar (notes) — Faza 2.

Bitta reja ichida bir nechta kichik qadam bo'lishi mumkin. Bu rejani
boshqarishni osonlashtiradi va "katta vazifa"ni bo'lib bajarishga yordam beradi.
"""
from __future__ import annotations

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.plan import Plan
from bot.models.subtask import Subtask


async def list_subtasks(session: AsyncSession, plan_id: int) -> list[Subtask]:
    res = await session.execute(
        select(Subtask).where(Subtask.plan_id == plan_id)
        .order_by(Subtask.position, Subtask.id)
    )
    return res.scalars().all()


async def add_subtask(session: AsyncSession, plan_id: int, title: str) -> Subtask:
    title = (title or "").strip()[:300]
    pos = await session.scalar(
        select(func.coalesce(func.max(Subtask.position), 0)).where(
            Subtask.plan_id == plan_id
        )
    ) or 0
    st = Subtask(plan_id=plan_id, title=title, position=pos + 1)
    session.add(st)
    await session.commit()
    await session.refresh(st)
    return st


async def toggle_subtask(session: AsyncSession, subtask_id: int) -> Subtask | None:
    st = await session.get(Subtask, subtask_id)
    if not st:
        return None
    st.completed = not st.completed
    await session.commit()
    await session.refresh(st)
    return st


async def delete_subtask(session: AsyncSession, subtask_id: int) -> bool:
    st = await session.get(Subtask, subtask_id)
    if not st:
        return False
    await session.delete(st)
    await session.commit()
    return True


async def subtask_progress(session: AsyncSession, plan_id: int) -> tuple[int, int]:
    """(bajarilgan, jami) subtasklar."""
    total = await session.scalar(
        select(func.count(Subtask.id)).where(Subtask.plan_id == plan_id)
    ) or 0
    done = await session.scalar(
        select(func.count(Subtask.id)).where(
            and_(Subtask.plan_id == plan_id, Subtask.completed == True)  # noqa: E712
        )
    ) or 0
    return done, total


async def set_plan_note(session: AsyncSession, plan_id: int, user_id: int,
                        note: str) -> Plan | None:
    res = await session.execute(
        select(Plan).where(and_(Plan.id == plan_id, Plan.user_id == user_id))
    )
    plan = res.scalar_one_or_none()
    if not plan:
        return None
    plan.notes = (note or "").strip()[:2000] or None
    await session.commit()
    await session.refresh(plan)
    return plan


def render_subtasks(subtasks: list[Subtask]) -> str:
    if not subtasks:
        return ""
    lines = ["\n📋 <b>Qadamlar:</b>"]
    for s in subtasks:
        mark = "✅" if s.completed else "⬜️"
        lines.append(f"  {mark} {s.title}")
    done = sum(1 for s in subtasks if s.completed)
    lines.append(f"<i>({done}/{len(subtasks)} bajarildi)</i>")
    return "\n".join(lines)
