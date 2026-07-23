"""
Global sozlamalar xizmati (feature flags).

Admin panelidan yoqilib/o'chiriladigan global bayroqlar shu yerda saqlanadi.
Har bir bayroq `app_settings` jadvalidagi bitta qatorda (key/value) yashaydi.
Har bir request'da DB'ga bormaslik uchun jarayonda kichkina in-memory kesh
saqlanadi — kesh yozish operatsiyasida yangilanadi va boshqa jarayonlar (masalan
alohida deploy qilingan bot process) uchun ham DB'ga oldindan yozib qo'yiladi.

Hozir yagona bayroq:
  • `group_perms_menu_enabled` — Do'stlar/guruhlar sahifasidagi "🛡 Ruxsatlar"
    tugmasini yoqadi/o'chiradi. TRUE (default) — normal xatti-harakat,
    foydalanuvchilar ruxsatlarni o'zlari boshqaradi. FALSE — tugma yashiriladi
    va ruxsat qulflari e'tibordan chetlashtiriladi, ya'ni guruh a'zolari
    bir-birining reja va odatlarini avtomatik ko'radi.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.app_setting import AppSetting


# ─────────────────────────────────────────────────────────────
#  KEY nomlari
# ─────────────────────────────────────────────────────────────
KEY_GROUP_PERMS_MENU = "group_perms_menu_enabled"


# Modul darajasidagi kesh. `None` — kesh hali yuklanmagan; `str|""` — DB'dagi qiymat;
# lekin biz `key`ni umuman topmasak `_MISSING` bilan belgilaymiz (default qo'llaniladi).
_MISSING = object()
_cache: dict[str, object] = {}


def _to_bool(v: object, default: bool) -> bool:
    if v is _MISSING or v is None:
        return default
    s = str(v).strip().lower()
    if not s:
        return default
    return s in ("1", "true", "yes", "on", "y", "t")


async def get_setting(session: AsyncSession, key: str) -> Optional[str]:
    """Yordamchi: xom qiymatni oladi (kesh bilan). Yozuv bo'lmasa None."""
    if key in _cache:
        v = _cache[key]
        return None if v is _MISSING else v  # type: ignore[return-value]
    row = await session.get(AppSetting, key)
    val: object = row.value if row else _MISSING
    _cache[key] = val
    return None if val is _MISSING else val  # type: ignore[return-value]


async def set_setting(session: AsyncSession, key: str, value: Optional[str]) -> None:
    """Yordamchi: qiymatni yozib qo'yadi (upsert) va keshni yangilaydi."""
    row = await session.get(AppSetting, key)
    if row is None:
        row = AppSetting(key=key, value=value)
        session.add(row)
    else:
        row.value = value
    await session.commit()
    _cache[key] = value if value is not None else _MISSING


# ─────────────────────────────────────────────────────────────
#  BAYROQLAR: guruh ruxsatlar menyusi
# ─────────────────────────────────────────────────────────────
async def is_group_perms_menu_enabled(session: AsyncSession) -> bool:
    """
    TRUE (default) — foydalanuvchilar Do'stlar sahifasida "🛡 Ruxsatlar" tugmasini
    ko'radi va o'z ma'lumotlarini kim ko'rishini boshqaradi.
    FALSE — tugma yashirinadi va guruh a'zolari bir-birining reja/odatlarini
    to'g'ridan-to'g'ri (ruxsatsiz) ko'radi.
    """
    v = await get_setting(session, KEY_GROUP_PERMS_MENU)
    return _to_bool(v, default=True)


async def set_group_perms_menu_enabled(session: AsyncSession, enabled: bool) -> None:
    """Bayroqni yozib qo'yadi. Kesh avtomatik yangilanadi."""
    await set_setting(session, KEY_GROUP_PERMS_MENU, "1" if enabled else "0")


def invalidate_cache() -> None:
    """Testlar yoki tashqi yangilanish uchun keshni tozalash."""
    _cache.clear()
