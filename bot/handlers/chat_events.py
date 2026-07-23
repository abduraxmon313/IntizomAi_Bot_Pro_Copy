"""
Bot Telegram chatlarga qo'shilgan/chiqarilganini kuzatuvchi handlerlar.

Maqsad: `bot_chats` jadvalini yangilab turish. WebApp guruh egasi
"Statistikani Telegram guruhga yuborish" tugmasini bosgach, bot faqat shu
jadvaldagi chatlarni Telegram guruh nomzodi sifatida ko'radi.

`my_chat_member` update — Telegram Bot API'ning kanonik yo'li. Bot chatga
qo'shilganda, chiqarilganda yoki huquqlari o'zgarganda yuboriladi.

`message` update — chat sarlavhasi o'zgarishi bo'lsa kesh yangilanadi (30
daqiqada bir marta, throttled).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    CallbackQuery, ChatMemberUpdated, InlineKeyboardButton,
    InlineKeyboardMarkup, Message,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.bot_chat import BotChat

logger = logging.getLogger(__name__)
router = Router()


def group_menu_keyboard() -> InlineKeyboardMarkup:
    """
    Bot guruhda faqat SHU 2 ta tugmani ko'rsatadi:
      • 📊 Umumiy hisobot — WebApp'ning "Do'stlar → Test yuborish" digest'i kabi
        ishlaydi; guruh bilan bog'langan WebApp guruhning bugungi jamoaviy
        hisobotini shu Telegram chatga yuboradi. Faqat Premium foydalanuvchi
        chaqira oladi.
      • 📞 Bog'lanish — admin/kanal bilan aloqa.

    Boshqa hech qanday shaxsiy tugmalar (statusim/rejalarim/hisobot/reja qo'shish/
    Premium) guruhda KO'RSATILMAYDI va guruh xabarlariga bot javob bermaydi.
    """
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Umumiy hisobot", callback_data="grp_report")],
        [InlineKeyboardButton(text="📞 Bog'lanish", callback_data="grp_contact")],
    ])


GROUP_WELCOME_TEXT = (
    "👋 <b>Salom, jamoa!</b>\n\n"
    "Men — <b>Intizom AI</b>. Odatda men foydalanuvchi bilan shaxsiy chatda "
    "ishlayman (rejalar, odatlar, statistika). Guruhda esa quyidagi ikkita "
    "amalni bajaraman:\n\n"
    "📊 <b>Umumiy hisobot</b> — guruhingizga bog'langan WebApp guruhning "
    "bugungi jamoaviy natijasini shu chatga leaderboard shaklida yuboraman.\n"
    "<i>(Guruh egasi Mini App → Do'stlar bo'limida guruh yaratib, uni shu "
    "Telegram chatga bog'lashi kerak. Bu amal Premium egasiga tegishli.)</i>\n\n"
    "📞 <b>Bog'lanish</b> — admin va rasmiy kanalga havolalar.\n\n"
    "Shaxsiy rejalar va Mini App bilan ishlash uchun botga "
    "<b>shaxsiy chat</b>dan yozing 👇"
)


# Chat sarlavhasi keshini yangilash oralig'i — chatdagi har xabarda emas, 30
# daqiqada bir marta, DB yozuvlari yukini kamaytirish uchun.
_TITLE_REFRESH_MIN = timedelta(minutes=30)


def _extract_can_send(new_member) -> bool:
    """
    Yangi holatdan botning xabar yuborish huquqini aniqlaydi.
      • 'administrator' — `can_post_messages` yoki umumiy huquq berilsa TRUE.
      • 'member' — default; guruh sozlamalari (faqat adminlar) buni to'sishi
        mumkin, ammo Telegram Bot API buni my_chat_member payloadida bermaydi
        — real yuborishda `Forbidden: bot can't send messages to this chat`
        xatosi orqali bilib olamiz.
      • Boshqa statuslar (left/kicked/restricted) — FALSE.
    """
    status = getattr(new_member, "status", None)
    if status in ("member", "creator"):
        return True
    if status == "administrator":
        # Aiogram 3.x ChatMemberAdministrator obyekti — can_send_messages yo'q,
        # can_post_messages faqat kanal uchun. Guruh admini default xabar
        # yuborishi mumkin, shuning uchun TRUE.
        return True
    if status == "restricted":
        # Restricted member — can_send_messages bayrog'i bo'lishi mumkin.
        return bool(getattr(new_member, "can_send_messages", False))
    return False


@router.my_chat_member()
async def on_bot_membership_change(
    event: ChatMemberUpdated, session: AsyncSession,
):
    """
    Bot chatga qo'shildi/chiqarildi/huquqlari o'zgardi.

    Faqat group/supergroup chatlar kuzatiladi — WebApp digest guruh chatlariga
    yuboriladi (channel/private uchun bu funksiya kerak emas).
    """
    chat = event.chat
    if chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        return

    new_status = event.new_chat_member.status if event.new_chat_member else "left"
    old_status = event.old_chat_member.status if event.old_chat_member else "left"
    can_send = _extract_can_send(event.new_chat_member) if event.new_chat_member else False

    row = await session.get(BotChat, chat.id)
    now = datetime.utcnow()
    was_absent = row is None or row.bot_status not in ("member", "administrator", "creator")

    if row is None:
        row = BotChat(
            chat_id=chat.id,
            chat_type=chat.type,
            chat_title=(chat.title or "")[:200] or None,
            chat_username=(chat.username or "")[:64] or None,
            bot_status=new_status,
            bot_can_send=can_send,
            added_by=(event.from_user.id if event.from_user else None),
            added_at=now,
            updated_at=now,
            last_seen_at=now,
        )
        session.add(row)
    else:
        row.chat_type = chat.type
        if chat.title:
            row.chat_title = chat.title[:200]
        row.chat_username = (chat.username or "")[:64] or None
        row.bot_status = new_status
        row.bot_can_send = can_send
        row.updated_at = now
        # Bot yangi qo'shilyapti — `added_by` yozuvsiz qolmasin (ilgari left/kicked
        # bo'lgan bo'lishi mumkin).
        if new_status in ("member", "administrator", "creator") and event.from_user:
            row.added_by = event.from_user.id

    try:
        await session.commit()
        logger.info(
            f"bot_chat: chat_id={chat.id} status={new_status} "
            f"title={(chat.title or '')[:40]!r} by={event.from_user.id if event.from_user else '-'}"
        )
    except Exception as e:
        await session.rollback()
        logger.warning(f"bot_chat commit xato: {e}")

    # ── WELCOME xabari ─────────────────────────────────────────────────
    # Bot guruhga YANGI qo'shildi (avval yo'q yoki left/kicked edi, endi
    # member/administrator/creator). Guruhga qisqacha tanishtiruv xabari
    # va 2 ta tugma (Umumiy hisobot / Bog'lanish) yuboramiz. Bu guruh
    # foydalanuvchilari uchun yagona ruxsat etilgan interfeys — bot boshqa
    # menyu tugmalarini guruhda ko'rsatmaydi va shaxsiy komandalarga
    # javob bermaydi (shaxsiy handlerlar ChatType.PRIVATE bilan cheklangan).
    became_member = new_status in ("member", "administrator", "creator")
    if was_absent and became_member and can_send:
        try:
            await event.bot.send_message(
                chat.id,
                GROUP_WELCOME_TEXT,
                parse_mode="HTML",
                reply_markup=group_menu_keyboard(),
                disable_web_page_preview=True,
            )
            logger.info(f"👋 group welcome sent: chat_id={chat.id}")
        except (TelegramForbiddenError, TelegramBadRequest) as e:
            # Bot yozish huquqiga ega emas yoki chat topilmadi — jim o'tamiz.
            logger.info(f"group welcome skip chat_id={chat.id}: {e}")
        except Exception as e:
            logger.warning(f"group welcome xato chat_id={chat.id}: {type(e).__name__}: {e}")


# DIQQAT: bu catch-all handler'ni SPETSIFIK guruh handlerlaridan (yuqoridagi
# `group_start`, `group_report_message`, `grp_*_callback`) OLDIN ro'yxatga
# olmang — aks holda ular hech qachon ishga tushmaydi. Filtrlarga
# istisnolar (`~F.text.in_({...})` va `~F.text.startswith("/")`) qo'shildi
# — shu tariqa `/start` va tugma matnlari SPETSIFIK handlerlarga o'tadi va
# bu yerga faqat qolgan (foydali bo'lmagan) guruh xabarlari keladi.
_GROUP_RESERVED_TEXTS = {"📊 Umumiy hisobot", "📞 Bog'lanish"}


@router.message(
    F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP}),
    # Buyruq (masalan /start) yoki bizning ajratilgan tugma matni bo'lsa —
    # bu handler ISHLAMAYDI, spetsifik handlerlarga o'tadi.
    ~(F.text.startswith("/") | F.text.in_(_GROUP_RESERVED_TEXTS)),
)
async def on_group_message(message: Message, session: AsyncSession):
    """
    Guruh xabari (buyruq/tugma matni bo'lmagan) — bot_chats.chat_title/username
    keshini yangilash (throttled).

    Bot boshqa hech nima QILMAYDI (guruhda javob bermaydi). Bu shunchaki chat
    sarlavhasi o'zgarganda yoki bot avval yozib qolinmagan chatda paydo bo'lsa
    kesh to'ldirilishi uchun.
    """
    chat = message.chat
    row = await session.get(BotChat, chat.id)
    now = datetime.utcnow()

    if row is None:
        # my_chat_member bo'yicha yozuv yo'q edi — hozir yaratamiz. Bu ilgari
        # botni qo'shgan xabar o'tkazib yuborilgan holat uchun himoya.
        row = BotChat(
            chat_id=chat.id,
            chat_type=chat.type,
            chat_title=(chat.title or "")[:200] or None,
            chat_username=(chat.username or "")[:64] or None,
            bot_status="member",
            bot_can_send=True,
            added_at=now,
            updated_at=now,
            last_seen_at=now,
        )
        session.add(row)
    else:
        # Throttle: 30 daqiqadan bir marta yozuvni yangilaymiz.
        if row.last_seen_at and (now - row.last_seen_at) < _TITLE_REFRESH_MIN:
            # Sarlavha o'zgargan bo'lsa BARIBIR yangilaymiz (kam uchraydi).
            if chat.title and row.chat_title != chat.title[:200]:
                row.chat_title = chat.title[:200]
            else:
                return
        else:
            row.last_seen_at = now
            if chat.title:
                row.chat_title = chat.title[:200]
            row.chat_username = (chat.username or "")[:64] or None
            row.chat_type = chat.type

    try:
        await session.commit()
    except Exception as e:
        await session.rollback()
        logger.debug(f"bot_chat title refresh skip: {e}")



# ═══════════════════════════════════════════════════════════════════════
#  GURUH HANDLERLARI: /start, "📊 Umumiy hisobot", callbacks
# ═══════════════════════════════════════════════════════════════════════
# Guruh chatlarida bot faqat ushbu 2 ta amalni bajaradi:
#   1) 📊 Umumiy hisobot — WebApp guruh digest'ini shu Telegram chatga yuboradi
#      (faqat Premium foydalanuvchi chaqira oladi)
#   2) 📞 Bog'lanish — admin/kanal havolalari
#
# Shaxsiy tugmalar (Statusim/Rejalarim/Hisobot/Premium/...) BLOKLANGAN — ular
# ChatType.PRIVATE filtri bilan cheklangan (bot/handlers/status.py, plan.py,
# subscribe.py, report.py, admin.py).


_GROUP_PREMIUM_REQ = (
    "📊 <b>Umumiy hisobot</b> — faqat Premium egalari uchun.\n\n"
    "Botga shaxsiy chatingizda <code>/start</code> yuboring va "
    "«💎 Premium» tugmasini bosing."
)

_GROUP_NOT_LINKED = (
    "📊 <b>Bu Telegram guruh WebApp'da bog'lanmagan.</b>\n\n"
    "Guruh egasi Mini App → <b>Do'stlar</b> bo'limida guruh yaratib, uni shu "
    "Telegram chatga bog'lashi kerak. Shundan keyin «📊 Umumiy hisobot» "
    "tugmasi jamoangizning bugungi natijasini shu chatga yuboradi."
)


async def _fetch_linked_group(session: AsyncSession, chat_id: int):
    """
    Berilgan Telegram chat_id'ga bog'langan WebApp Group topadi (yoki None).
    Bog'lanish Mini App → Do'stlar bo'limida (guruh sozlamalari) amalga oshadi.
    """
    from bot.models.group import Group
    res = await session.execute(
        select(Group).where(Group.telegram_chat_id == chat_id)
    )
    return res.scalars().first()


@router.message(CommandStart(), F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP}))
async def group_start(message: Message):
    """
    Guruhda /start — welcome xabari va 2 ta tugma. Bot shaxsiy menyu tugmalarini
    (statusim/rejalarim/premium/...) guruhda ko'rsatmaydi.
    """
    try:
        await message.answer(
            GROUP_WELCOME_TEXT,
            parse_mode="HTML",
            reply_markup=group_menu_keyboard(),
            disable_web_page_preview=True,
        )
    except (TelegramForbiddenError, TelegramBadRequest) as e:
        logger.info(f"group /start reply skip chat_id={message.chat.id}: {e}")


# Guruhda "📊 Umumiy hisobot" matn tugmasi VA /hisobot buyrug'i.
# Ikkalasi ham bir xil funksiyaga yo'l ochadi (decorator stacking).
@router.message(
    Command("hisobot"),
    F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP}),
)
@router.message(
    F.text == "📊 Umumiy hisobot",
    F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP}),
)
async def group_report_message(message: Message, session: AsyncSession):
    """
    Guruh a'zosi tugma matnini yozsa yoki /hisobot buyrug'ini bosgach — digest'ni
    yuboramiz. Callback varianti bilan mantiq aynan bir xil.
    """
    await _run_group_report(
        session, message.chat.id, message.from_user.id, message.bot,
        reply_target=message,
    )


@router.callback_query(F.data == "grp_report")
async def grp_report_callback(callback: CallbackQuery, session: AsyncSession):
    """
    📊 Umumiy hisobot inline tugmasi bosildi. Guruh chatidan bo'lishi kerak;
    Premium foydalanuvchilargagina ruxsat beriladi.
    """
    if callback.message is None or callback.message.chat is None:
        await callback.answer("Chat aniqlanmadi.", show_alert=True)
        return
    if callback.message.chat.type not in ("group", "supergroup"):
        await callback.answer("Bu tugma faqat guruhlarda ishlaydi.", show_alert=True)
        return

    ok, alert_msg = await _run_group_report(
        session, callback.message.chat.id, callback.from_user.id, callback.bot,
        reply_target=None,
    )
    # Foydalanuvchiga qisqa toast — chat yuqorisida
    await callback.answer(alert_msg or ("✅ Hisobot yuborildi" if ok else "Xato"), show_alert=not ok)


@router.callback_query(F.data == "grp_contact")
async def grp_contact_callback(callback: CallbackQuery):
    """
    📞 Bog'lanish inline tugmasi bosildi (guruhda). Kontakt tugmalarini
    (admin, kanal) shu chatga yuboradi.
    """
    from bot.keyboards.subscribe_keys import contact_keyboard
    try:
        await callback.message.answer(
            "📞 <b>Bog'lanish</b>\n\nQuyidagidan birini tanlang 👇",
            parse_mode="HTML",
            reply_markup=contact_keyboard(),
            disable_web_page_preview=True,
        )
    except (TelegramForbiddenError, TelegramBadRequest) as e:
        await callback.answer(f"Xatolik: {e}", show_alert=True)
        return
    await callback.answer()


# ─── "Batafsil" — foydalanuvchining bugungi barcha reja va odatlari ───
# Digest xabari tagida `👤 <name>` inline tugmalari ko'rinadi. Har biri
# bosilganda shu handler ushbu foydalanuvchining bugungi reja va odat
# ro'yxatini alohida (reply message) qilib guruhga yuboradi — kim qaysi
# rejani BAJARDI, qaysi rejani BAJARMADI aniq ko'rinadi.

# Reja statusi → ikon (`bot.models.plan.PlanStatus` qiymatlariga mos).
_PLAN_STATUS_ICON = {
    "done":    "✅",
    "failed":  "❌",
    "pending": "⏳",
}
_UZ_WEEKDAYS_LOWER = [
    "dushanba", "seshanba", "chorshanba", "payshanba",
    "juma", "shanba", "yakshanba",
]
_UZ_MONTHS_LOWER = [
    "yanvar", "fevral", "mart", "aprel", "may", "iyun",
    "iyul", "avgust", "sentyabr", "oktyabr", "noyabr", "dekabr",
]


def _fmt_uz_date(d) -> str:
    """`23-iyul (payshanba)` formatida sana."""
    return f"{d.day}-{_UZ_MONTHS_LOWER[d.month - 1]} ({_UZ_WEEKDAYS_LOWER[d.weekday()]})"


def _html_escape(text: str) -> str:
    return (
        (text or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


@router.callback_query(F.data.startswith("grp_det_"))
async def grp_details_callback(callback: CallbackQuery, session: AsyncSession):
    """
    Guruh digest'idagi bitta a'zoning "Batafsil" tugmasi bosildi. Shu a'zoning
    bugungi rejalari (holati bilan: ✅/❌/⏳) va odatlarini (bajarilgan/kutilyapti)
    ko'rsatuvchi javob xabarni digestga reply qilib yuboradi.

    XAVFSIZLIK: callback data'da user_id kelayapti — hacker uni almashtirib
    guruh a'zosi bo'lmagan foydalanuvchining shaxsiy ma'lumotini ololmasligi
    uchun target user AYNAN shu Telegram guruhga bog'langan WebApp Group
    a'zosi ekanligini tekshiramiz.
    """
    # 1. Callback data'dan user_id ni ajratib olamiz.
    try:
        target_user_id = int(callback.data.rsplit("_", 1)[-1])
    except (ValueError, IndexError):
        await callback.answer("Xato so'rov.", show_alert=True)
        return

    # 2. Kontekst: bu callback aynan qaysi Telegram chatidan kelyapti?
    if callback.message is None or callback.message.chat is None:
        await callback.answer("Chat aniqlanmadi.", show_alert=True)
        return
    if callback.message.chat.type not in ("group", "supergroup"):
        await callback.answer("Bu tugma faqat guruhda ishlaydi.", show_alert=True)
        return
    chat_id = callback.message.chat.id

    # 3. Guruh (WebApp Group) ni topamiz.
    group = await _fetch_linked_group(session, chat_id)
    if group is None:
        await callback.answer(
            "Bu Telegram guruh WebApp'da bog'lanmagan.", show_alert=True,
        )
        return

    # 4. Target user AYNAN shu guruh a'zosi ekanligini tekshiramiz (IDOR himoya).
    from bot.models.group import GroupMember
    from bot.models.user import User
    is_member = (await session.execute(
        select(GroupMember).where(
            (GroupMember.group_id == group.id)
            & (GroupMember.user_id == target_user_id)
        )
    )).scalars().first()
    if is_member is None:
        await callback.answer(
            "Bu foydalanuvchi guruh a'zosi emas.", show_alert=True,
        )
        return

    # 5. Target user obyektini yuklaymiz.
    target = await session.get(User, target_user_id)
    if target is None:
        await callback.answer("Foydalanuvchi topilmadi.", show_alert=True)
        return

    # 6. Bugungi rejalar va odatlarni yig'amiz.
    from datetime import datetime as _dt
    from bot.config import TIMEZONE as _TZ
    from bot.services.plan_service import get_today_plans
    from bot.services.habit_service import get_user_habits, habit_snapshot

    today = _dt.now(_TZ).date()
    plans = await get_today_plans(session, target)
    habits = await get_user_habits(session, target)
    habit_snaps = [await habit_snapshot(session, h) for h in habits]
    # Bugun rejalashtirilgan (due_today) odatlar — asosiy ko'rsatkich.
    habits_today = [s for s in habit_snaps if s.get("due_today")]

    # 7. HTML matn quramiz.
    name = (target.display_name or target.full_name or "Foydalanuvchi").strip() or "Foydalanuvchi"
    header = f"📋 <b>{_html_escape(name)}</b> — {_fmt_uz_date(today)}"
    lines: list[str] = [header, ""]

    # ── Rejalar bloki ────────────────────────────────────────
    if plans:
        # Sanoq: bajarilgan / jami
        done_count = sum(1 for p in plans if str(getattr(p.status, "value", p.status)) == "done")
        lines.append(f"📝 <b>Rejalar</b> ({done_count}/{len(plans)}):")
        for p in plans:
            status_val = str(getattr(p.status, "value", p.status) or "pending")
            icon = _PLAN_STATUS_ICON.get(status_val, "⏳")
            time_prefix = f"{p.scheduled_time} " if p.scheduled_time else ""
            lines.append(f"  {icon} {time_prefix}{_html_escape(p.title)}")
    else:
        lines.append("📝 <b>Rejalar:</b> bugun reja qo'shmagan")

    lines.append("")

    # ── Odatlar bloki ────────────────────────────────────────
    if habits_today:
        done_habits = sum(1 for s in habits_today if s.get("done_today"))
        lines.append(f"🎯 <b>Odatlar</b> ({done_habits}/{len(habits_today)}):")
        for s in habits_today:
            icon = "✅" if s.get("done_today") else "⭕"
            emoji = s.get("icon") or "•"
            lines.append(f"  {icon} {emoji} {_html_escape(s.get('title') or '')}")
    else:
        lines.append("🎯 <b>Odatlar:</b> bugun rejalashtirilmagan")

    # ── Qo'shimcha ma'lumot ─────────────────────────────────
    streak = int(target.streak or 0)
    if streak > 0:
        lines.append("")
        lines.append(f"🔥 Streak: <b>{streak} kun</b>")

    html = "\n".join(lines)

    # 8. Javobni digestga reply qilib yuboramiz.
    try:
        await callback.message.reply(
            html,
            parse_mode="HTML",
            disable_web_page_preview=True,
            disable_notification=True,  # Guruh a'zolarini spam qilmaslik uchun
        )
    except (TelegramForbiddenError, TelegramBadRequest) as e:
        await callback.answer(f"Xatolik: {e}", show_alert=True)
        return

    await callback.answer()


async def _run_group_report(
    session: AsyncSession,
    chat_id: int,
    telegram_user_id: int,
    bot,
    *,
    reply_target=None,
) -> tuple[bool, str | None]:
    """
    "📊 Umumiy hisobot" mantig'ining yagona amalga oshirilishi (callback va matn
    handlerlaridan chaqiriladi).

    Qadamlar:
      1. Chaqiruvchi userni topamiz.
      2. User Premium bo'lishi shart.
      3. Ushbu Telegram chatga bog'langan WebApp Group bor bo'lishi kerak.
      4. `send_digest_for_group(..., is_test=False)` chaqiramiz — u digestni
         group.telegram_chat_id ga (aynan shu chatga) yuboradi.

    Qaytaradi: (ok: bool, alert_msg: Optional[str]).
      • Muvaffaqiyat: (True, None) — chaqiruvchiga toast ko'rsatiladi.
      • Rad etish: (False, "sabab") — foydalanuvchiga alert (show_alert=True) ko'rsatiladi.
    """
    from bot.services.premium_service import user_is_premium
    from bot.services.user_service import get_user_by_telegram_id
    from bot.services.digest_service import send_digest_for_group

    caller = await get_user_by_telegram_id(session, telegram_user_id)
    if caller is None or not user_is_premium(caller):
        if reply_target is not None:
            try:
                await reply_target.reply(_GROUP_PREMIUM_REQ, parse_mode="HTML")
            except Exception:
                pass
        # Callback uchun ham toast (qisqartirilgan)
        return False, "💎 Faqat Premium foydalanuvchilar uchun. Botga shaxsiy chatda /start yuboring."

    group = await _fetch_linked_group(session, chat_id)
    if group is None:
        if reply_target is not None:
            try:
                await reply_target.reply(_GROUP_NOT_LINKED, parse_mode="HTML")
            except Exception:
                pass
        return False, "Bu guruh WebApp'da bog'lanmagan (guruh egasi bog'lashi kerak)."

    # Digest'ni jo'natish — is_test=False, chunki bu haqiqiy so'rov.
    result = await send_digest_for_group(session, group, bot=bot, is_test=False)
    if result.ok:
        return True, None

    # Digest chiqmadi (masalan a'zolar yo'q yoki matn bo'sh).
    reason = result.reason or "Yuboriladigan mazmun yo'q."
    return False, f"Hisobot yuborilmadi: {reason}"
