"""
Guruh digest xizmati — WebApp guruhning bugungi reja+odat statistikasini
bog'langan Telegram guruhga leaderboard shaklida yuboradi.

Asosiy funksiyalar:
  • list_telegram_candidates(...) — bot va guruh egasi ikkalasi ham a'zo
    bo'lgan Telegram chatlar ro'yxati (WebApp UI'da tanlashi uchun).
  • send_digest_for_group(...) — bitta guruh uchun digestni tayyorlab yuborish
    (test tugmasidan yoki cron'dan chaqiriladi).
  • send_due_digests(...) — schedulerdan har daqiqada chaqiriladi; joriy vaqtga
    mos guruhlarni topib yuboradi.

Xavfsizlik: WebApp API endpoint'lari egalikni tekshirgach shu funksiyalarni
chaqiradi. Bu modul o'zi qo'shimcha auth tekshirmaydi — u ishonchli chaqiruv
konteksida ishlaydi.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Optional

from aiogram import Bot
from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramRetryAfter,
)
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import BOT_TOKEN, TIMEZONE
from bot.models.bot_chat import BotChat
from bot.models.group import Group, GroupMember
from bot.models.user import User
from bot.services.group_service import _bulk_today_summary
from database.db import AsyncSessionLocal

# Digest xabaridagi "Batafsil" tugmalar uchun MAX foydalanuvchi soni.
# Ko'proq bo'lsa xabar juda uzun tugmalar bilan to'lib ketardi va
# Telegram inline_keyboard chegarasi (~100 tugma) yaqinlashardi.
_MAX_DETAIL_BUTTONS = 10

logger = logging.getLogger(__name__)

# Telegram Bot API bir chatga xabar yuborishning "burst" limiti — soniyada 1
# ta. Bir daqiqada 20 ta digest bo'lsa muammo emas; lekin katta hajmda cron
# ichida yuborishni asta-sekin qilish uchun kichik pauza.
_SEND_PAUSE = 0.15


# ─────────────────────────────────────────────────────────────
#  Yordamchi: Bot instansiya boshqaruvi
# ─────────────────────────────────────────────────────────────
class _BotContext:
    """
    `Bot(token=...)` ni bir marta yaratib, kontekst tugagach yopadi.

    WebApp jarayonida bot alohida polling qilayotgan bo'lishi mumkin — u
    bilan aloqasiz alohida Bot obyektini yaratamiz (getChatMember/sendMessage
    kabi metodlar server tomonda, session xavfsiz).
    """
    def __init__(self, existing: Optional[Bot] = None):
        self._existing = existing
        self._owned: Optional[Bot] = None

    async def __aenter__(self) -> Bot:
        if self._existing is not None:
            return self._existing
        self._owned = Bot(token=BOT_TOKEN)
        return self._owned

    async def __aexit__(self, exc_type, exc, tb):
        if self._owned is not None:
            try:
                await self._owned.session.close()
            except Exception:
                pass


# ─────────────────────────────────────────────────────────────
#  Candidates: bot + user birga bo'lgan Telegram chatlar
# ─────────────────────────────────────────────────────────────
@dataclass
class CandidateChat:
    chat_id: int
    chat_title: str
    chat_type: str
    is_selected: bool  # ushbu WebApp guruhga hozir bog'langanmi
    can_send: bool     # bot xabar yubora oladimi (member/admin va can_send)


async def list_telegram_candidates(
    session: AsyncSession,
    user_telegram_id: int,
    *,
    selected_chat_id: Optional[int] = None,
    bot: Optional[Bot] = None,
    max_chats: int = 50,
) -> list[CandidateChat]:
    """
    Bot ham, foydalanuvchi (guruh egasi) ham a'zo bo'lgan Telegram guruhlar.

    Bot faqat `bot_chats` jadvalidagi active statusdagi (member/administrator/
    creator) chatlarni ko'radi. Har birida `getChatMember(chat_id, user_id)`
    chaqirilib, foydalanuvchi u yerda member/admin/creator ekanligi tekshiriladi.

    `max_chats` — ish yukini cheklash uchun (foydalanuvchi juda ko'p chatda
    bo'lsa ham ~50 ta bilan cheklanadi; keyingi versiyada qidirish qo'shiladi).
    """
    # Faqat bot xabar yuborishi mumkin bo'lgan chatlar.
    active_statuses = ("member", "administrator", "creator")
    rows = (await session.execute(
        select(BotChat).where(
            and_(
                BotChat.bot_status.in_(active_statuses),
                BotChat.chat_type.in_(("group", "supergroup")),
            )
        ).order_by(BotChat.updated_at.desc()).limit(max_chats)
    )).scalars().all()

    if not rows:
        return []

    async with _BotContext(bot) as b:
        # getChatMember chaqiruvlarini parallel qilamiz (max 8 ta bir vaqtda).
        sem = asyncio.Semaphore(8)

        async def _check(row: BotChat) -> Optional[CandidateChat]:
            async with sem:
                try:
                    cm = await b.get_chat_member(row.chat_id, user_telegram_id)
                except (TelegramBadRequest, TelegramForbiddenError) as e:
                    logger.debug(
                        f"candidate skip chat={row.chat_id} user={user_telegram_id}: {e}"
                    )
                    return None
                except TelegramRetryAfter as e:
                    await asyncio.sleep(min(e.retry_after + 1, 10))
                    try:
                        cm = await b.get_chat_member(row.chat_id, user_telegram_id)
                    except Exception:
                        return None
                except Exception as e:
                    logger.debug(
                        f"candidate error chat={row.chat_id}: {type(e).__name__}: {e}"
                    )
                    return None

                if cm.status not in (
                    ChatMemberStatus.MEMBER,
                    ChatMemberStatus.ADMINISTRATOR,
                    ChatMemberStatus.CREATOR,
                ):
                    return None

                return CandidateChat(
                    chat_id=row.chat_id,
                    chat_title=row.chat_title or f"Chat #{row.chat_id}",
                    chat_type=row.chat_type,
                    is_selected=(row.chat_id == selected_chat_id),
                    can_send=bool(row.bot_can_send),
                )

        results = await asyncio.gather(*(_check(r) for r in rows))

    out = [c for c in results if c is not None]
    # Tanlangan chat har doim tepada, keyin sarlavha bo'yicha alifbo tartibida.
    out.sort(key=lambda c: (not c.is_selected, (c.chat_title or "").lower()))
    return out


# ─────────────────────────────────────────────────────────────
#  Digest xabari qurish
# ─────────────────────────────────────────────────────────────
_MEDALS = ("🥇", "🥈", "🥉")


def _score_key(s: dict) -> float:
    """
    Leaderboard uchun bajarilish foizi.
      • Reja va odat bajarilish yig'indisi (mavjud bo'lgan).
      • Umuman reja/odat bo'lmagan a'zolar 0 ga tushadi (past reyting).
    """
    plans_t = int(s.get("plans_total") or 0)
    plans_d = int(s.get("plans_done") or 0)
    habits_t = int(s.get("habits_total") or 0)
    habits_d = int(s.get("habits_done_today") or 0)
    total_items = plans_t + habits_t
    if total_items <= 0:
        return 0.0
    total_done = plans_d + habits_d
    return round(100.0 * total_done / total_items, 1)


def _escape(text: str) -> str:
    """Telegram HTML uchun minimal escape (< > &)."""
    return (
        (text or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _member_line(
    rank_symbol: str,
    name: str,
    summary: dict,
    streak: int,
    telegram_id: int,
    *,
    mention_html: bool,
) -> str:
    """
    Bitta a'zo uchun leaderboard qatori.
    `mention_html=True` bo'lsa ismni <a href="tg://user?id=..."> bilan mentionlaymiz.
    """
    display = _escape(name)
    if mention_html and telegram_id:
        display = f'<a href="tg://user?id={int(telegram_id)}">{display}</a>'

    p_t = int(summary.get("plans_total") or 0)
    p_d = int(summary.get("plans_done") or 0)
    h_t = int(summary.get("habits_total") or 0)
    h_d = int(summary.get("habits_done_today") or 0)

    parts: list[str] = []
    if p_t > 0:
        mark = "✅" if p_d >= p_t else ""
        parts.append(f"{p_d}/{p_t} reja {mark}".strip())
    if h_t > 0:
        mark = "🔥" if h_d >= h_t else ""
        parts.append(f"{h_d}/{h_t} odat {mark}".strip())
    if not parts:
        parts.append("bugun rejasiz")

    tail = ""
    if streak > 0:
        tail = f"  ·  🔥{int(streak)}"

    return f"{rank_symbol} <b>{display}</b>  —  {'  ·  '.join(parts)}{tail}"


UZ_WEEKDAYS = [
    "dushanba", "seshanba", "chorshanba", "payshanba",
    "juma", "shanba", "yakshanba",
]
UZ_MONTHS = [
    "yanvar", "fevral", "mart", "aprel", "may", "iyun",
    "iyul", "avgust", "sentyabr", "oktyabr", "noyabr", "dekabr",
]


def _uz_date(d: date) -> str:
    return f"{d.day}-{UZ_MONTHS[d.month - 1]} ({UZ_WEEKDAYS[d.weekday()]})"


@dataclass
class DigestBuild:
    """
    Digest xabari uchun to'liq ma'lumot to'plami:
      • html   — Telegram xabari matni (parse_mode="HTML")
      • active — bugun ish qilgan a'zolar ranked ro'yxati (User obyektlari
                 bilan). Bu ro'yxatdan chaqiruvchi kod inline "Batafsil"
                 tugmalarini yasashi mumkin (har bir foydalanuvchi uchun).
    """
    html: str
    active: list[User]


def _build_detail_keyboard(active_users: list[User]) -> Optional[InlineKeyboardMarkup]:
    """
    Digest xabari tagida joylashadigan "Batafsil" inline tugmalari.
    Har bir aktiv (bugun ish qilgan) foydalanuvchi uchun bitta tugma:
      "👤 <name>"  →  callback_data="grp_det_<user_id>"

    Tugmalar 2 tadan bir qatorda joylashtiriladi. `_MAX_DETAIL_BUTTONS` dan
    ortiq bo'lsa keyingilari o'tkazib yuboriladi (Telegram xabari juda
    uzun bo'lmasin).
    """
    if not active_users:
        return None
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for u in active_users[:_MAX_DETAIL_BUTTONS]:
        raw = (u.display_name or u.full_name or "Foydalanuvchi").strip() or "Foydalanuvchi"
        # Telegram inline button matni cheklovlar bilan (odatda ~64 belgigacha
        # to'g'ri ko'rinadi). ~14 belgi guruh a'zolari ismini yaxshi ko'rsatadi.
        display = raw[:14]
        row.append(InlineKeyboardButton(
            text=f"👤 {display}",
            callback_data=f"grp_det_{u.id}",
        ))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return InlineKeyboardMarkup(inline_keyboard=rows) if rows else None


async def build_digest(
    session: AsyncSession, group: Group,
) -> Optional[DigestBuild]:
    """
    Berilgan WebApp guruh uchun bugungi digest matnini VA aktiv a'zolar
    ro'yxatini birga quradi. None qaytarsa — a'zolar yo'q yoki chat bog'lanmagan;
    yuborilmaydi.

    Chaqiruvchi kod (`send_digest_for_group`) qaytgan `active` ro'yxatidan
    inline "Batafsil" tugmalarini yasab, digest xabari bilan birga yuboradi.
    """
    if not group.telegram_chat_id:
        return None

    # A'zolar (users bilan) — leaderboard uchun barchasini olamiz.
    rows = (await session.execute(
        select(GroupMember, User)
        .join(User, User.id == GroupMember.user_id)
        .where(GroupMember.group_id == group.id)
        .order_by(GroupMember.joined_at)
    )).all()

    if not rows:
        return None

    user_ids = [u.id for _gm, u in rows]
    summaries = await _bulk_today_summary(session, user_ids)

    # A'zolarni bajarilish foizi bo'yicha kamayish tartibida saralaymiz.
    ranked = []
    for _gm, u in rows:
        s = summaries.get(u.id) or {}
        pct = _score_key(s)
        # Total items = 0 bo'lgan a'zolar (bugun umuman reja/odat qo'shmagan)
        # oxirida turadi.
        has_items = (int(s.get("plans_total") or 0) + int(s.get("habits_total") or 0)) > 0
        ranked.append({
            "user": u,
            "summary": s,
            "pct": pct,
            "has_items": has_items,
        })

    # Bugun umuman ish bo'lmaganlarni pastroqqa surish.
    ranked.sort(key=lambda r: (not r["has_items"], -r["pct"], -(r["user"].streak or 0)))

    show_zero = bool(group.digest_show_zero)
    mention = bool(group.digest_mention)
    today = datetime.now(TIMEZONE).date()

    # Sarlavha
    lines: list[str] = [
        f"📊 <b>IntizomAi hisobot</b> — {_uz_date(today)}",
        f"👥 <b>{_escape(group.name)}</b>",
        "",
    ]

    # Aktiv qatnashuvchilar (bugun items bor)
    active_rows = [r for r in ranked if r["has_items"]]
    idle_rows = [r for r in ranked if not r["has_items"]]

    if not active_rows and not show_zero:
        # Hech kim hech narsa qilmagan va "0 larni ko'rsatmaslik" yoqilgan —
        # digest yubormaymiz (spam bo'lmasin).
        return None

    if not active_rows:
        lines.append("😴 Bugun guruhda hech kim reja/odat qo'shmagan.")
        lines.append("")
    else:
        # Top qatnashuvchilar
        total_pct_sum = 0.0
        for i, r in enumerate(active_rows):
            symbol = _MEDALS[i] if i < 3 else "  •"
            name = (
                (r["user"].display_name or r["user"].full_name or "Foydalanuvchi").strip()
                or "Foydalanuvchi"
            )
            lines.append(_member_line(
                symbol, name, r["summary"], int(r["user"].streak or 0),
                r["user"].telegram_id, mention_html=mention,
            ))
            total_pct_sum += r["pct"]

        avg = round(total_pct_sum / max(1, len(active_rows)), 1)
        lines.append("")
        lines.append(f"📈 O'rtacha bajarilish: <b>{avg:g}%</b>")

    # Bugun hech narsa qilmaganlar (agar show_zero=TRUE)
    if idle_rows and show_zero:
        names = []
        for r in idle_rows[:10]:
            n = (
                (r["user"].display_name or r["user"].full_name or "Foydalanuvchi").strip()
                or "Foydalanuvchi"
            )
            if mention and r["user"].telegram_id:
                n = f'<a href="tg://user?id={int(r["user"].telegram_id)}">{_escape(n)}</a>'
            else:
                n = _escape(n)
            names.append(n)
        extra = f" +{len(idle_rows) - 10} kishi" if len(idle_rows) > 10 else ""
        lines.append("")
        lines.append(f"😴 Bugun ish yo'q: {', '.join(names)}{extra}")

    lines.append("")
    lines.append("💪 Ertaga davom etaylik!")
    lines.append("")
    lines.append("<i>👇 Har bir a'zoning batafsil hisobotini ko'rish uchun tugmani bosing.</i>")

    return DigestBuild(
        html="\n".join(lines),
        active=[r["user"] for r in active_rows],
    )


async def build_digest_html(
    session: AsyncSession, group: Group,
) -> Optional[str]:
    """
    Backward-compat shim. Boshqa chaqiruvchilar (masalan test / cron) faqat
    HTML matnini kutayotgan bo'lishi mumkin. Bu funksiya yangi
    `build_digest(...)` ni chaqirib, HTML qismini qaytaradi.
    """
    result = await build_digest(session, group)
    return result.html if result else None


# ─────────────────────────────────────────────────────────────
#  Yuborish (test / cron)
# ─────────────────────────────────────────────────────────────
@dataclass
class SendResult:
    ok: bool
    reason: str = ""
    should_unlink: bool = False  # Telegram xatosidan keyin auto-unlink kerakmi


async def send_digest_for_group(
    session: AsyncSession, group: Group,
    *,
    bot: Optional[Bot] = None,
    is_test: bool = False,
) -> SendResult:
    """
    Berilgan guruh uchun digestni Telegram chatga yuboradi.
    `is_test=True` bo'lsa xabar boshiga "🧪 Test hisobot" prefiksi qo'yiladi va
    `digest_last_sent_at` YANGILANMAYDI (haqiqiy digest deb hisoblanmaydi).
    """
    if not group.telegram_chat_id:
        return SendResult(ok=False, reason="Telegram chat bog'lanmagan.")
    if not group.digest_enabled and not is_test:
        return SendResult(ok=False, reason="Digest o'chirilgan.")

    built = await build_digest(session, group)
    if not built:
        return SendResult(ok=False, reason="Yuboriladigan mazmun yo'q.")

    html = built.html
    if is_test:
        html = "🧪 <b>Test hisobot</b>\n\n" + html

    # Har bir aktiv a'zo uchun "Batafsil" inline tugma — bosilsa bot shu
    # foydalanuvchining bugungi barcha rejalari va odatlarini alohida javob
    # xabarida ko'rsatadi (chat_events.py `grp_details_callback` ushlaydi).
    reply_markup = _build_detail_keyboard(built.active)

    async with _BotContext(bot) as b:
        try:
            await b.send_message(
                group.telegram_chat_id, html,
                parse_mode="HTML",
                disable_web_page_preview=True,
                reply_markup=reply_markup,
            )
            reason = "ok"
            should_unlink = False
        except TelegramRetryAfter as e:
            await asyncio.sleep(min(e.retry_after + 1, 10))
            try:
                await b.send_message(
                    group.telegram_chat_id, html,
                    parse_mode="HTML",
                    disable_web_page_preview=True,
                    reply_markup=reply_markup,
                )
                reason = "ok"
                should_unlink = False
            except Exception as e2:
                reason = f"retry_after_fail: {type(e2).__name__}"
                should_unlink = False
        except TelegramForbiddenError as e:
            # Bot chatdan chiqarilgan / bloklangan — auto-unlink.
            reason = f"forbidden: {e}"
            should_unlink = True
        except TelegramBadRequest as e:
            # chat_not_found, bot_kicked_from_chat, chat_write_forbidden, ...
            msg = str(e).lower()
            should_unlink = any(k in msg for k in (
                "chat not found", "chat_not_found",
                "kicked", "not enough rights",
                "chat_write_forbidden", "bot was blocked",
                "supergroup was deactivated",
            ))
            reason = f"bad_request: {e}"
        except Exception as e:
            reason = f"error: {type(e).__name__}: {e}"
            should_unlink = False

    # Natija saqlash (test bo'lmasa)
    if not is_test:
        if reason == "ok":
            group.digest_last_sent_at = datetime.utcnow()
            group.digest_last_error = None
        else:
            group.digest_last_error = reason[:300]
            if should_unlink:
                logger.warning(
                    f"digest auto-unlink group={group.id} chat={group.telegram_chat_id}: {reason}"
                )
                group.digest_enabled = False
                # `telegram_chat_id` ni saqlab qolamiz — foydalanuvchi qayta yoqishi
                # mumkin. Faqat digest_enabled=FALSE qilamiz.
        try:
            await session.commit()
        except Exception:
            await session.rollback()

    return SendResult(
        ok=(reason == "ok"),
        reason=reason,
        should_unlink=should_unlink,
    )


# ─────────────────────────────────────────────────────────────
#  Cron: joriy vaqtga mos digestlarni yuborish
# ─────────────────────────────────────────────────────────────
async def send_due_digests(bot: Optional[Bot] = None) -> None:
    """
    APScheduler har daqiqada chaqiradi. Joriy Toshkent vaqtiga (HH:MM) mos
    keluvchi guruhlarni topib, digestni yuboradi.

    Duplikat yuborishdan himoya: agar shu daqiqada `digest_last_sent_at`
    allaqachon yozilgan bo'lsa — o'tkazib yuboriladi (bir minut ichida qayta
    ishga tushirilsa spam bo'lmasin).
    """
    now = datetime.now(TIMEZONE)
    hhmm = now.strftime("%H:%M")

    async with AsyncSessionLocal() as session:
        due = (await session.execute(
            select(Group).where(
                and_(
                    Group.digest_enabled == True,          # noqa: E712
                    Group.digest_time == hhmm,
                    Group.telegram_chat_id.is_not(None),
                )
            )
        )).scalars().all()

        if not due:
            return

        # Bir daqiqa ichida takrorlanishdan himoya: last_sent_at hozirgi
        # daqiqa bilan bir xil bo'lsa o'tkazamiz.
        window_start = datetime.utcnow() - timedelta(minutes=1)
        to_send = [
            g for g in due
            if not g.digest_last_sent_at or g.digest_last_sent_at < window_start
        ]
        if not to_send:
            return

        logger.info(f"digest: {len(to_send)} ta guruhga yuborish (soat {hhmm})")

        async with _BotContext(bot) as b:
            for g in to_send:
                try:
                    await send_digest_for_group(session, g, bot=b, is_test=False)
                except Exception as e:
                    logger.warning(f"digest group={g.id} xato: {e}")
                await asyncio.sleep(_SEND_PAUSE)
