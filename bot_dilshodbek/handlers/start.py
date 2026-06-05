"""
Dilshodbek bot — /start va "Siz uchun yangilik" oqimi.

Bu eski "IntizomAI_bot" ning asl xatti-harakati: foydalanuvchi /start bossa
bitta tugma chiqadi, tugmani bossa — yangilik (asosiy botga ko'chish va
promokod) habari yuboriladi.

Qo'shimcha: /start bosgan foydalanuvchi UMUMIY bazaga yoziladi
(get_or_create_user) — shu tariqa admin keyinroq ularga xabar yubora oladi.
"""
from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.services.user_service import get_or_create_user
from bot_dilshodbek.keyboards import NEWS_BUTTON_TEXT, news_keyboard

router = Router()


NEWS_MESSAGE = """Assalomu alaykum! 👋

IntizomAI bo'yicha muhim yangilik bor.

Botdan foydalanishni yanada qulay qilish maqsadida bot manzili @intizomAi_bot ga o'zgartirildi.

✅ Xavotir olmang, barcha ma'lumotlaringiz saqlanib qolgan:

rejalaringiz
statistikangiz
streaklaringiz
yutuqlaringiz

Hech narsa o'chib ketmagan.

Botdan foydalanishni davom ettirish uchun:

@intizomAi_bot ga o'ting
Start tugmasini bosing
Avvalgidek foydalanishda davom eting

🚀 Shuningdek, botga yangi funksiyalar qo'shildi va ular muntazam ravishda yangilanib boradi.

💎 IntizomAI endi obuna tizimi orqali ishlaydi.

Siz bizning dastlabki foydalanuvchilarimizdan biri bo'lganingiz uchun minnatdorchilik sifatida hisobingizga +1 oy bepul obuna qo'shib beriladi.

🎁 Promokod:
ASROR

Qo'llab-quvvatlaganingiz uchun rahmat. Birgalikda yanada kuchli IntizomAI quramiz! 🔥"""


@router.message(CommandStart())
async def start_handler(message: Message, state: FSMContext, session: AsyncSession):
    # Admin broadcast holatida bo'lsa ham /start uni tozalaydi.
    await state.clear()

    # Foydalanuvchini umumiy bazaga yozamiz/yangilaymiz (admin xabar yubora olishi uchun).
    try:
        await get_or_create_user(
            session=session,
            telegram_id=message.from_user.id,
            full_name=message.from_user.full_name,
            username=message.from_user.username or "",
        )
    except Exception:
        # Bazaga yozish ishlamasa ham foydalanuvchiga javob beramiz.
        pass

    await message.answer("Tugmani bosing 👇", reply_markup=news_keyboard())


@router.message(F.text == NEWS_BUTTON_TEXT)
async def news_handler(message: Message):
    await message.answer(NEWS_MESSAGE, reply_markup=news_keyboard())
