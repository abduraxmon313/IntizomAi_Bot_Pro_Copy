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
  • build_user_detail_html(...) — bitta a'zoning bugungi tafsilotini (bajarilgan
    va bajarilmagan rejalar+odatlar ro'yxati) HTML shaklida qaytaradi
    (guruhdagi inline tugma bosilganda chaqiriladi).

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
from bot.models.habit import Habit, HabitLog
from bot.models.plan import Plan, PlanStatus
from bot.models.user import User
from bot.services.group_service import _bulk_today_summary
from bot.services.premium_service import user_is_premium
from database.db import AsyncSessionLocal

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


def _score_key(s: dict) -> float:
    """
    Bajarilish foizi (reja + odat).
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


def _totals(s: dict) -> tuple[int, int]:
    """Bugungi 'bajarilgan/jami' (reja+odat qo'shilgan) qiymatlarini qaytaradi."""
    done = int(s.get("plans_done") or 0) + int(s.get("habits_done_today") or 0)
    total = int(s.get("plans_total") or 0) + int(s.get("habits_total") or 0)
    return done, total


def _escape(text: str) -> str:
    """Telegram HTML uchun minimal escape (< > &)."""
    return (
        (text or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _display_name(u: User) -> str:
    """A'zoning ko'rsatiladigan ismi (display_name > full_name > fallback)."""
    return (
        (u.display_name or u.full_name or "Foydalanuvchi").strip()
        or "Foydalanuvchi"
    )


def _name_html(u: User, *, mention: bool) -> str:
    """Ism HTML — mention yoqilgan bo'lsa <a href="tg://user?id=…">."""
    n = _escape(_display_name(u))
    if mention and u.telegram_id:
        return f'<a href="tg://user?id={int(u.telegram_id)}">{n}</a>'
    return n


def _name_html_with_premium(u: User, *, mention: bool) -> str:
    """
    Ism HTML + Premium bo'lsa yonida 💎 belgisi.
    Foydalanuvchi so'ragan: "manabu royhatda ham ism yonida olmos chiqsin
    agar premium bolsa".
    """
    n = _name_html(u, mention=mention)
    if user_is_premium(u):
        return f"{n} 💎"
    return n


UZ_WEEKDAYS = [
    "Dushanba", "Seshanba", "Chorshanba", "Payshanba",
    "Juma", "Shanba", "Yakshanba",
]
UZ_MONTHS = [
    "yanvar", "fevral", "mart", "aprel", "may", "iyun",
    "iyul", "avgust", "sentyabr", "oktyabr", "noyabr", "dekabr",
]


def _uz_date(d: date) -> str:
    """Masalan: "24-iyul (Juma)"."""
    return f"{d.day}-{UZ_MONTHS[d.month - 1]} ({UZ_WEEKDAYS[d.weekday()]})"


async def build_digest_html(
    session: AsyncSession, group: Group,
) -> Optional[str]:
    """
    Berilgan WebApp guruh uchun bugungi digest HTML matnini quradi.
    None qaytarsa — a'zolar yo'q yoki chat bog'lanmagan; yuborilmaydi.

    Yangi format (foydalanuvchi so'ragan tuzilma):
        📊 IntizomAi — Bugungi hisobot
        📅 24-iyul (Juma)
        👥 Guruh: Sinov

        ✅ Bajarganlar:
        🟢 Abduraxmon — 4/14

        ❌ Umuman bajarmaganlar:
        🔴 abdusattor — 0/1
        🔴 asror — 0/2

        ━━━━━━━━━━━━━━

        📈 Guruh faolligi: 9.5%
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

    # A'zolarni 3 guruhga ajratamiz:
    #   • done_rows      — bugun kamida bitta narsa bajargan (done >= 1)
    #   • undone_rows    — bugun rejalar/odatlar bor, lekin hech narsa qilmagan (done == 0, total > 0)
    #   • idle_rows      — bugun umuman reja/odat qo'shmagan (total == 0)
    done_rows: list[dict] = []
    undone_rows: list[dict] = []
    idle_rows: list[dict] = []
    for _gm, u in rows:
        s = summaries.get(u.id) or {}
        d, t = _totals(s)
        entry = {"user": u, "summary": s, "done": d, "total": t, "pct": _score_key(s)}
        if t <= 0:
            idle_rows.append(entry)
        elif d >= 1:
            done_rows.append(entry)
        else:
            undone_rows.append(entry)

    # Bajarganlar — done/total bo'yicha kamayish tartibida (yuqori foiz tepada).
    done_rows.sort(key=lambda r: (-r["pct"], -(r["user"].streak or 0)))
    # Bajarmaganlar — total (rejalar soni) bo'yicha kamayish tartibida.
    undone_rows.sort(key=lambda r: (-r["total"], -(r["user"].streak or 0)))

    show_zero = bool(group.digest_show_zero)
    mention = bool(group.digest_mention)
    today = datetime.now(TIMEZONE).date()

    if not done_rows and not undone_rows and not show_zero:
        # Hech kim hech narsa qilmagan/rejalashtirmagan va idle'larni ko'rsatish
        # o'chirilgan — spam bo'lmasligi uchun digest yubormaymiz.
        return None

    # Sarlavha bloki (foydalanuvchi so'ragan aynan formatda).
    lines: list[str] = [
        "📊 <b>IntizomAi — Bugungi hisobot</b>",
        f"📅 {_uz_date(today)}",
        f"👥 Guruh: <b>{_escape(group.name)}</b>",
        "",
    ]

    # ── Bajarganlar bloki (premium userlar yoniga 💎 qo'shiladi)
    if done_rows:
        lines.append("✅ <b>Bajarganlar:</b>")
        for r in done_rows:
            u = r["user"]
            name = _name_html_with_premium(u, mention=mention)
            lines.append(f"🟢 {name} — {r['done']}/{r['total']}")
        lines.append("")

    # ── Umuman bajarmaganlar bloki (premium userlar yoniga 💎 qo'shiladi)
    if undone_rows:
        lines.append("❌ <b>Umuman bajarmaganlar:</b>")
        for r in undone_rows:
            u = r["user"]
            name = _name_html_with_premium(u, mention=mention)
            lines.append(f"🔴 {name} — {r['done']}/{r['total']}")
        lines.append("")

    # ── Idle (bugun umuman reja/odat qo'shmagan) — faqat show_zero yoqilgan bo'lsa
    if idle_rows and show_zero:
        names = [
            _name_html_with_premium(r["user"], mention=mention)
            for r in idle_rows[:10]
        ]
        extra = f" +{len(idle_rows) - 10} kishi" if len(idle_rows) > 10 else ""
        lines.append(f"😴 <b>Bugun rejasiz:</b> {', '.join(names)}{extra}")
        lines.append("")

    # ── Faollik foizi (barcha a'zolar bo'yicha o'rtacha)
    #   Idle a'zolar hisobga OLINMAYDI (ular bugun umuman qatnashmadi) — faqat
    #   done_rows + undone_rows dagi haqiqiy qatnashuvchilar o'rtachasi.
    lines.append("━━━━━━━━━━━━━━")
    active = done_rows + undone_rows
    if active:
        avg = sum(r["pct"] for r in active) / len(active)
        lines.append(f"📈 Guruh faolligi: <b>{avg:.1f}%</b>")
    else:
        lines.append("📈 Guruh faolligi: <b>0%</b>")

    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────
#  Digest inline keyboard — har bir a'zo uchun tugma
# ─────────────────────────────────────────────────────────────
# Callback data limiti Telegram tomonidan 64 baytga cheklangan. Format:
#   du:<group_id>:<user_id>   — "digest user" (a'zo tafsiloti)
#   dgb:<group_id>            — "digest back" (a'zo tafsilotidan hisobotga qaytish)
# Butun sonlar, shuning uchun 64 bayt limitidan ancha ostida.
DGST_USER_CB_PREFIX = "du"
DGST_BACK_CB_PREFIX = "dgb"


def build_user_detail_back_keyboard(group_id: int) -> InlineKeyboardMarkup:
    """
    A'zo tafsilotidan guruh hisobotiga qaytish uchun bitta tugmali keyboard.
    Bosilganda `chat_events.py`dagi `grp_digest_back_callback` ishga tushadi
    va xabarni qayta guruh hisobotiga aylantiradi.
    """
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text="⬅️ Orqaga",
            callback_data=f"{DGST_BACK_CB_PREFIX}:{int(group_id)}",
        ),
    ]])


async def build_digest_keyboard(
    session: AsyncSession, group: Group,
) -> Optional[InlineKeyboardMarkup]:
    """
    Digest xabari ostiga qo'yiladigan inline keyboard — har bir a'zo uchun
    "👤 Ism  •  X/Y" ko'rinishida tugma. Bosilganda o'sha a'zoning bugungi
    bajargan va bajarmagan rejalari/odatlari ro'yxatiga o'tiladi.

    A'zolar ikki qatorda joylashadi (kichik ekran uchun sig'ish). Umuman
    reja/odat qo'shmaganlar tugmasi ham chiqadi — "0/0" bilan.
    """
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

    # A'zolarni tartiblash: avval bajarganlar (done>=1), keyin bajarmaganlar,
    # oxirida idle (total=0). Har bir kategoriya ichida done/total bo'yicha.
    def _sort_key(item):
        _gm, u = item
        s = summaries.get(u.id) or {}
        d, t = _totals(s)
        if t <= 0:
            bucket = 2
        elif d >= 1:
            bucket = 0
        else:
            bucket = 1
        return (bucket, -_score_key(s), -(u.streak or 0))

    rows.sort(key=_sort_key)

    # Har bir a'zo uchun tugma — matn: "👤 <name> · X/Y"
    kb_rows: list[list[InlineKeyboardButton]] = []
    row_buf: list[InlineKeyboardButton] = []
    # Nom uzunligini cheklaymiz — Telegram tugma matnini juda uzun ko'rsata olmaydi.
    NAME_MAX = 14
    # Maksimum 30 ta a'zo tugmasi — juda katta guruhlar uchun UI portlab
    # ketmasligi uchun (kelajakda pagination qo'shiladi).
    MAX_BUTTONS = 30
    for _gm, u in rows[:MAX_BUTTONS]:
        s = summaries.get(u.id) or {}
        d, t = _totals(s)
        name = _display_name(u)
        if len(name) > NAME_MAX:
            name = name[: NAME_MAX - 1] + "…"
        emoji = "🟢" if (t > 0 and d >= 1) else ("🔴" if t > 0 else "⚪️")
        label = f"{emoji} {name} · {d}/{t}"
        cb = f"{DGST_USER_CB_PREFIX}:{group.id}:{u.id}"
        row_buf.append(InlineKeyboardButton(text=label, callback_data=cb))
        if len(row_buf) >= 2:
            kb_rows.append(row_buf)
            row_buf = []
    if row_buf:
        kb_rows.append(row_buf)

    if not kb_rows:
        return None

    return InlineKeyboardMarkup(inline_keyboard=kb_rows)


# ─────────────────────────────────────────────────────────────
#  Bitta a'zoning bugungi tafsiloti
# ─────────────────────────────────────────────────────────────
async def _get_user_today_items(
    session: AsyncSession, user_id: int,
) -> tuple[list[tuple[str, bool]], list[tuple[str, bool]]]:
    """
    Foydalanuvchining bugungi rejalar va odatlarini nom+bajarilish bilan qaytaradi.
    Qaytadi: (plans, habits) — har biri [(title, is_done), ...].
    """
    today = datetime.now(TIMEZONE).date()

    plan_rows = (await session.execute(
        select(Plan.title, Plan.status)
        .where(and_(Plan.user_id == user_id, Plan.plan_date == today))
        .order_by(Plan.scheduled_time.nullslast(), Plan.id)
    )).all()
    plans = [(row[0] or "-", row[1] == PlanStatus.done) for row in plan_rows]

    # Odatlar — arxivlanmaganlarni oldindan olib, bugungi HabitLog bilan JOIN.
    habit_rows = (await session.execute(
        select(Habit.id, Habit.title)
        .where(and_(Habit.user_id == user_id, Habit.archived == False))  # noqa: E712
        .order_by(Habit.sort_order, Habit.id)
    )).all()
    if habit_rows:
        habit_ids = [row[0] for row in habit_rows]
        done_ids = set()
        for (hid,) in (await session.execute(
            select(HabitLog.habit_id).where(and_(
                HabitLog.habit_id.in_(habit_ids),
                HabitLog.log_date == today,
            ))
        )).all():
            done_ids.add(int(hid))
        habits = [(row[1] or "-", int(row[0]) in done_ids) for row in habit_rows]
    else:
        habits = []

    return plans, habits


async def build_user_detail_html(
    session: AsyncSession, group: Group, user: User,
) -> str:
    """
    Bitta a'zo uchun bugungi tafsilotni HTML shaklida qaytaradi:

        👤 <name>  ·  🔥 5  ·  💎

        📊 Bugungi natija: 4/14

        ✅ Bajarilgan (4)
        🟢 Ingliz tili
        🟢 Kitob o'qish
        ...

        ━━━━━━━━━━━━━━

        ❌ Bajarilmagan (10)
        🔴 Ertalab yugurish
        ...
    """
    plans, habits = await _get_user_today_items(session, user.id)

    # Har bir item — (title, done). Rejalar va odatlarni birlashtirib, done/undone
    # ro'yxatlarini quramiz. Rejalar oxiriga "(reja)" belgisi qo'shilmaydi —
    # foydalanuvchi so'ragan sodda ko'rinish.
    done_items: list[str] = []
    undone_items: list[str] = []
    for title, is_done in plans:
        (done_items if is_done else undone_items).append(_escape(title))
    for title, is_done in habits:
        (done_items if is_done else undone_items).append(_escape(title))

    total_done = len(done_items)
    total_items = total_done + len(undone_items)

    # Sarlavha: 👤 ism 💎 (agar premium). Streak (🔥) endi ko'rsatilmaydi —
    # foydalanuvchi so'ragan: "ismni yonida olmos ozi yetadi".
    name = _escape(_display_name(user))
    if user_is_premium(user):
        header = f"👤 <b>{name}</b> 💎"
    else:
        header = f"👤 <b>{name}</b>"

    lines: list[str] = [
        header,
        "",
        f"📊 Bugungi natija: <b>{total_done}/{total_items}</b>",
        "",
    ]

    # ── Bajarilgan blok
    lines.append(f"✅ <b>Bajarilgan ({total_done})</b>")
    if done_items:
        for it in done_items:
            lines.append(f"🟢 {it}")
    else:
        lines.append("<i>— hech narsa yo'q</i>")

    # Ajratuvchi chiziq
    lines.append("")
    lines.append("━━━━━━━━━━━━━━")
    lines.append("")

    # ── Bajarilmagan blok
    lines.append(f"❌ <b>Bajarilmagan ({len(undone_items)})</b>")
    if undone_items:
        for it in undone_items:
            lines.append(f"🔴 {it}")
    else:
        lines.append("<i>— barchasi bajarildi, zo'r! 🔥</i>")

    if total_items == 0:
        # Foydalanuvchi bugun umuman reja/odat qo'shmagan
        lines = [
            header,
            "",
            "😴 Bugun hali reja yoki odat qo'shmagan.",
        ]

    return "\n".join(lines)


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

    html = await build_digest_html(session, group)
    if not html:
        return SendResult(ok=False, reason="Yuboriladigan mazmun yo'q.")

    if is_test:
        html = "🧪 <b>Test hisobot</b>\n\n" + html

    # Har bir a'zo uchun tafsilotni ochish tugmasi (inline keyboard).
    # Xatoga qarshi himoya — keyboard qurishda muammo bo'lsa, digest matn holida
    # baribir yuboriladi.
    try:
        keyboard = await build_digest_keyboard(session, group)
    except Exception as e:
        logger.warning(f"digest keyboard xato group={group.id}: {type(e).__name__}: {e}")
        keyboard = None

    async with _BotContext(bot) as b:
        try:
            await b.send_message(
                group.telegram_chat_id, html,
                parse_mode="HTML",
                disable_web_page_preview=True,
                reply_markup=keyboard,
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
                    reply_markup=keyboard,
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
