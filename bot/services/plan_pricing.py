"""
Obuna tariflarining "effective" (amaldagi) narxlari — DB override + config
default'lari birlashtirilgan holda.

Strategiya:
  1. `bot/config.py`'dagi `SUBSCRIPTION_PLANS` — turi (kalit, kunlar, emoji, teg)
     hech qachon o'zgarmaydigan default katalog.
  2. Admin `/admin → Premium → 💰 Tariflar narxi` orqali biror tarif narxini
     o'zgartirsa, `subscription_plan_overrides` jadvaliga override yoziladi.
  3. Aktiv (foydalanuvchi/keyboard/checkout) so'rovlar `get_effective_plans()` /
     `get_effective_plan()` chaqiradi — bu sinxron xotira keshini o'qiydi.
  4. Kesh startup'da va har `set_plan_price` chaqiruvidan keyin yangilanadi.

To'lov tizimi ta'siri:
  • Buyurtma (`PaymentOrder`) yaratilganda amount SHU PAYTDAGI effective narx
    bo'yicha qulflanadi. Admin keyin narxni o'zgartirsa ham eski buyurtma
    o'z summasini saqlaydi — webhook'dagi `_amounts_match` teshigi yo'q.
  • Foydalanuvchi obuna oynasini har qachon ochsa, o'sha lahzadagi effective
    narxni ko'radi.

Xato bardoshliligi:
  • Kesh doim boshlanishida config default'lariga to'ldiriladi.
  • DB refresh xato bersa (masalan jadval hali yaratilmagan bo'lsa) — cache
    default holida qoladi, `get_effective_plans` xato bermaydi.
"""
from __future__ import annotations

import asyncio
import copy
import logging
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import SUBSCRIPTION_PLANS
from bot.models.plan_override import SubscriptionPlanOverride

logger = logging.getLogger(__name__)


# Xotira keshi: {plan_key: {"title", "days", "price", "emoji", "tag"}}
_effective_plans: dict = copy.deepcopy(SUBSCRIPTION_PLANS)
_cache_lock = asyncio.Lock()
_cache_ready = False


def _merge_overrides(overrides: list[SubscriptionPlanOverride]) -> dict:
    """
    Config default'lari ustiga DB override qiymatlarini qo'shadi.
    Narxdan tashqari, admin tugma yozuvi va bezakni ham (title/emoji/tag) o'zgartira oladi.
    """
    merged = copy.deepcopy(SUBSCRIPTION_PLANS)
    for ov in overrides or []:
        if ov.plan_key not in merged:
            continue
        merged[ov.plan_key] = dict(merged[ov.plan_key])
        if ov.price is not None and ov.price >= 0:
            merged[ov.plan_key]["price"] = int(ov.price)
        # Tugma yozuvi va bezaklari — bo'sh bo'lmasa default'ni almashtiradi.
        if getattr(ov, "title", None):
            merged[ov.plan_key]["title"] = ov.title
        if getattr(ov, "emoji", None):
            merged[ov.plan_key]["emoji"] = ov.emoji
        if getattr(ov, "tag", None) is not None:
            # tag bo'sh string bo'lsa ham override qilamiz (admin tegni o'chirmoqchi
            # bo'lishi mumkin) — buni "-" belgi bilan ifodalash mumkin. Bo'sh string
            # tegni bekor qilish deb qaraladi.
            merged[ov.plan_key]["tag"] = "" if ov.tag == "-" else ov.tag
    return merged


async def refresh_plans_cache(session: AsyncSession) -> None:
    """DB dan override qiymatlarini o'qib effective plan keshini yangilaydi."""
    global _effective_plans, _cache_ready
    async with _cache_lock:
        try:
            res = await session.execute(select(SubscriptionPlanOverride))
            rows = list(res.scalars().all())
            _effective_plans = _merge_overrides(rows)
            _cache_ready = True
            if rows:
                logger.info(
                    f"plan_pricing: {len(rows)} ta override yuklandi "
                    f"({', '.join(f'{r.plan_key}={r.price}' for r in rows)})"
                )
        except Exception as e:
            # Jadval hali yaratilmagan yoki DB tayyor emas — default'da qolamiz.
            logger.warning(f"plan_pricing: cache refresh xato: {type(e).__name__}: {e}")


def get_effective_plans() -> dict:
    """Sync: joriy amaldagi tariflar (DB override + config default'lari)."""
    return _effective_plans


def get_effective_plan(plan_key: str) -> Optional[dict]:
    return _effective_plans.get(plan_key)


async def set_plan_meta(
    session: AsyncSession,
    plan_key: str,
    *,
    price: Optional[int] = None,
    title: Optional[str] = None,
    tag: Optional[str] = None,
    emoji: Optional[str] = None,
    updated_by: Optional[int] = None,
) -> None:
    """
    Tarif narxi va/yoki tugma yozuvini o'zgartiradi (yoki override yaratadi).
    None qiymat berilgan maydonlar o'zgarmaydi (avvalgi override yoki default qoladi).
    Keshni yangilaydi — keyingi barcha o'qishlar yangi qiymatlarni ko'radi.
    """
    if plan_key not in SUBSCRIPTION_PLANS:
        raise ValueError(f"Noma'lum tarif kaliti: {plan_key!r}")
    if price is not None:
        if not isinstance(price, int) or price < 0 or price > 100_000_000:
            raise ValueError("Narx 0..100 000 000 so'm oralig'ida bo'lishi kerak.")
    if title is not None:
        title = str(title).strip()[:64]
        if not title:
            raise ValueError("Nom bo'sh bo'lishi mumkin emas.")
    if tag is not None:
        tag = str(tag).strip()[:64]
    if emoji is not None:
        emoji = str(emoji).strip()[:8] or None

    row = await session.get(SubscriptionPlanOverride, plan_key)
    if row is None:
        # Yangi override qatori — narx berilmagan bo'lsa default narx bilan boshlaymiz
        # (row.price NOT NULL).
        row = SubscriptionPlanOverride(
            plan_key=plan_key,
            price=(price if price is not None else int(SUBSCRIPTION_PLANS[plan_key]["price"])),
            title=title,
            tag=tag,
            emoji=emoji,
            updated_by=updated_by,
        )
        session.add(row)
    else:
        if price is not None:
            row.price = price
        if title is not None:
            row.title = title
        if tag is not None:
            row.tag = tag
        if emoji is not None:
            row.emoji = emoji
        row.updated_by = updated_by
    await session.commit()
    await refresh_plans_cache(session)


# Backward-compat: narx-only helper (eski chaqiruvchilar ishlashda davom etishi uchun).
async def set_plan_price(
    session: AsyncSession,
    plan_key: str,
    price: int,
    updated_by: Optional[int] = None,
) -> None:
    await set_plan_meta(session, plan_key, price=price, updated_by=updated_by)


async def reset_plan_price(session: AsyncSession, plan_key: str) -> None:
    """Override'ni o'chiradi — narx/nom `bot/config.py`'dagi default'ga qaytadi."""
    row = await session.get(SubscriptionPlanOverride, plan_key)
    if row is not None:
        await session.delete(row)
        await session.commit()
    await refresh_plans_cache(session)


async def list_overrides(session: AsyncSession) -> dict[str, int]:
    """DB'dagi override'lar dict{plan_key: price} — admin ro'yxati uchun."""
    res = await session.execute(select(SubscriptionPlanOverride))
    return {r.plan_key: int(r.price) for r in res.scalars().all()}
