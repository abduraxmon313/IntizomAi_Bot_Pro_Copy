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
    InlineKeyboardMarkup, Message, ReplyKeyboardRemove,
)
from sqlalchemy import and_, select
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
            # Avval ReplyKeyboardRemove yuboramiz — guruhda reply keyboard
            # ko'rsatilmasligi kafolatlanadi.
            await event.bot.send_message(
                chat.id,
                GROUP_WELCOME_TEXT,
                parse_mode="HTML",
                reply_markup=ReplyKeyboardRemove(),
                disable_web_page_preview=True,
            )
            # Keyin inline tugmalarni alohida xabar sifatida yuboramiz
            await event.bot.send_message(
                chat.id,
                "👇 Quyidagi tugmalardan foydalaning:",
                parse_mode="HTML",
                reply_markup=group_menu_keyboard(),
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
    Reply Keyboard mavjud bo'lsa — olib tashlanadi (ReplyKeyboardRemove).
    """
    try:
        # Avval mavjud Reply Keyboard'ni olib tashlaymiz (agar bor bo'lsa)
        await message.answer(
            GROUP_WELCOME_TEXT,
            parse_mode="HTML",
            reply_markup=ReplyKeyboardRemove(),
            disable_web_page_preview=True,
        )
        # Keyin inline tugmalar bilan alohida xabar yuboramiz
        await message.answer(
            "👇 Quyidagi tugmalardan foydalaning:",
            parse_mode="HTML",
            reply_markup=group_menu_keyboard(),
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


# ─────────────────────────────────────────────────────────────
#  Guruh digest: a'zo tafsilotini ochish tugmasi (du:<group_id>:<user_id>)
# ─────────────────────────────────────────────────────────────
@router.callback_query(F.data.startswith("du:"))
async def grp_digest_user_callback(callback: CallbackQuery, session: AsyncSession):
    """
    Guruh digest xabari ostidagi "👤 A'zo · X/Y" tugmasi bosilganda:
      • Callback data: `du:<group_id>:<user_id>` (butun sonlar).
      • O'sha a'zoning bugungi bajarilgan/bajarilmagan rejalari+odatlari
        ro'yxatini digest xabarga REPLY qilib yuboramiz (ID_ni saqlaydi,
        guruh a'zolari birgalikda ko'ra oladi, digest joyida qoladi).

    Xavfsizlik/UX cheklovlari:
      • Faqat guruh chatlarida ishlaydi.
      • Har qanday a'zo har qanday a'zo tugmasini bosishi mumkin (digest
        allaqachon barcha a'zolarning umumiy son ko'rsatgichlarini omma
        oldida ko'rsatgan — batafsil ko'rish qo'shimcha maxfiy ma'lumot
        emas).
    """
    from bot.models.group import Group
    from bot.services.digest_service import (
        build_user_detail_html,
        build_user_detail_back_keyboard,
    )

    if callback.message is None or callback.message.chat is None:
        await callback.answer("Chat aniqlanmadi.", show_alert=True)
        return
    if callback.message.chat.type not in ("group", "supergroup"):
        await callback.answer("Bu tugma faqat guruhlarda ishlaydi.", show_alert=True)
        return

    # Callback data'ni parse qilamiz — `du:<gid>:<uid>`.
    try:
        _, gid_s, uid_s = callback.data.split(":", 2)
        group_id = int(gid_s)
        target_user_id = int(uid_s)
    except (ValueError, AttributeError):
        await callback.answer("Xato ma'lumot.", show_alert=True)
        return

    # Guruhni topamiz va Telegram chat_id mos kelishini tekshiramiz — boshqa
    # guruh tugmasini nusxa olib ko'chirish orqali kirmasin (audit safety).
    group = await session.get(Group, group_id)
    if group is None or group.telegram_chat_id != callback.message.chat.id:
        await callback.answer("Bu tugma bu chatga tegishli emas.", show_alert=True)
        return

    # A'zoni topamiz va guruhda ekanligini tekshiramiz.
    from bot.models.group import GroupMember
    from bot.models.user import User
    membership = (await session.execute(
        select(GroupMember, User)
        .join(User, User.id == GroupMember.user_id)
        .where(and_(
            GroupMember.group_id == group_id,
            GroupMember.user_id == target_user_id,
        ))
    )).first()
    if membership is None:
        await callback.answer("A'zo topilmadi.", show_alert=True)
        return
    _gm, target_user = membership

    try:
        html = await build_user_detail_html(session, group, target_user)
        back_kb = build_user_detail_back_keyboard(group_id)
    except Exception as e:
        logger.warning(
            f"user_detail xato group={group_id} user={target_user_id}: {type(e).__name__}: {e}"
        )
        await callback.answer("Tafsilotni olishda xatolik.", show_alert=True)
        return

    # Xabarni O'ZGARTIRAMIZ (edit_text) — reply emas. Foydalanuvchi so'ragan:
    # "hisobotda kimnidur ismini bossa ... osha matn ozgarsin va orqaga tugmasi
    # bolsin". Shu tariqa guruh chatida yangi xabarlar to'planib qolmaydi va
    # kontekst joyida qoladi.
    try:
        await callback.message.edit_text(
            html,
            parse_mode="HTML",
            disable_web_page_preview=True,
            reply_markup=back_kb,
        )
    except TelegramBadRequest as e:
        # "message is not modified" xatosi — bir xil user tugmasi ikki marta
        # bosilgan bo'lishi mumkin (jim o'tamiz).
        if "not modified" in str(e).lower():
            await callback.answer()
            return
        await callback.answer(f"Xatolik: {e}", show_alert=True)
        return
    except TelegramForbiddenError as e:
        await callback.answer(f"Xatolik: {e}", show_alert=True)
        return

    await callback.answer()


# ─────────────────────────────────────────────────────────────
#  A'zo tafsilotidan guruh hisobotiga qaytish (dgb:<group_id>)
# ─────────────────────────────────────────────────────────────
@router.callback_query(F.data.startswith("dgb:"))
async def grp_digest_back_callback(callback: CallbackQuery, session: AsyncSession):
    """
    A'zo tafsilotidan "⬅️ Orqaga" bosilganda — xabarni qayta guruh umumiy
    hisobotiga aylantiramiz (edit_text). Yangi digest kompleksi (matn +
    a'zolar tugmalari) shu vaqtdagi dolzarb ma'lumot bo'yicha qayta quriladi.
    """
    from bot.models.group import Group
    from bot.services.digest_service import (
        build_digest_html,
        build_digest_keyboard,
    )

    if callback.message is None or callback.message.chat is None:
        await callback.answer("Chat aniqlanmadi.", show_alert=True)
        return
    if callback.message.chat.type not in ("group", "supergroup"):
        await callback.answer("Bu tugma faqat guruhlarda ishlaydi.", show_alert=True)
        return

    try:
        _, gid_s = callback.data.split(":", 1)
        group_id = int(gid_s)
    except (ValueError, AttributeError):
        await callback.answer("Xato ma'lumot.", show_alert=True)
        return

    group = await session.get(Group, group_id)
    if group is None or group.telegram_chat_id != callback.message.chat.id:
        await callback.answer("Bu tugma bu chatga tegishli emas.", show_alert=True)
        return

    try:
        html = await build_digest_html(session, group)
        keyboard = await build_digest_keyboard(session, group)
    except Exception as e:
        logger.warning(
            f"digest rebuild xato group={group_id}: {type(e).__name__}: {e}"
        )
        await callback.answer("Hisobotni qayta qurishda xatolik.", show_alert=True)
        return

    if not html:
        # Bu holat kamdan-kam — digest allaqachon yuborilgan bo'lsa mazmun bor
        # bo'lishi kerak. Har qanday xatoga qarshi jim toast.
        await callback.answer("Hisobot yangilanishga tayyor emas.", show_alert=True)
        return

    try:
        await callback.message.edit_text(
            html,
            parse_mode="HTML",
            disable_web_page_preview=True,
            reply_markup=keyboard,
        )
    except TelegramBadRequest as e:
        if "not modified" in str(e).lower():
            await callback.answer()
            return
        await callback.answer(f"Xatolik: {e}", show_alert=True)
        return
    except TelegramForbiddenError as e:
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
