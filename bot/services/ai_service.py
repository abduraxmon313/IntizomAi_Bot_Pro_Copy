import json
import os
import tempfile
import logging
from datetime import datetime, timedelta
from openai import AsyncOpenAI
from bot.config import OPENAI_API_KEY, TIMEZONE

logger = logging.getLogger(__name__)

client = AsyncOpenAI(api_key=OPENAI_API_KEY)


async def transcribe_voice(file_bytes: bytes) -> str:
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
            tmp.write(file_bytes)
            tmp_path = tmp.name

        with open(tmp_path, "rb") as audio_file:
            transcript = await client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file,
            )

        result = transcript.text.strip()
        logger.info(f"✅ Whisper natija: '{result}'")
        return result

    except Exception as e:
        logger.error(f"❌ Whisper xatosi: {type(e).__name__}: {str(e)}")
        raise e

    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)


def _has_cyrillic(s: str) -> bool:
    return any(0x0400 <= ord(c) <= 0x04FF for c in (s or ""))


async def _translate_titles_to_latin(titles: list[str]) -> list[str]:
    """
    Kirill sarlavhalar ro'yxatini o'zbek (lotin) tiliga BITTA GPT chaqiruvida
    tarjima qiladi. Xatolik yoki mos kelmaslikda xavfsiz fallback ("Reja").
    Kirish tartibi bilan bir xil uzunlikdagi ro'yxat qaytaradi.
    """
    if not titles:
        return []
    # Bitta so'rov: JSON massiv qaytarishni so'raymiz (indeks bo'yicha mos).
    numbered = "\n".join(f"{i + 1}. {t}" for i, t in enumerate(titles))
    try:
        resp = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": (
                    "Sen tarjimonsan. Berilgan sarlavhalarni o'zbek tiliga (FAQAT "
                    "lotin harflarida) tarjima qil. FAQAT JSON massiv qaytar — "
                    "kirish tartibida, xuddi shuncha element. Boshqa hech narsa yozma. "
                    'Masalan: ["Uyg\'onish","Kitob o\'qish"]'
                )},
                {"role": "user", "content": numbered},
            ],
            temperature=0.05,
        )
        raw = (resp.choices[0].message.content or "").strip()
        # ``` bloklarini tozalaymiz
        if "```" in raw:
            parts = raw.split("```")
            if len(parts) >= 2:
                raw = parts[1]
                if raw.startswith("json"):
                    raw = raw[4:]
                raw = raw.strip()
        s = raw.find("[")
        e = raw.rfind("]") + 1
        arr = json.loads(raw[s:e]) if (s != -1 and e > s) else []
    except Exception as ex:
        logger.warning(f"⚠️ Batch tarjima xatosi: {type(ex).__name__}: {ex}")
        arr = []

    out: list[str] = []
    for i, original in enumerate(titles):
        cand = arr[i] if (isinstance(arr, list) and i < len(arr) and isinstance(arr[i], str)) else ""
        cand = (cand or "").strip()
        # Bo'sh yoki hali ham kirill bo'lsa — fallback
        if not cand or _has_cyrillic(cand):
            cand = "Reja"
        out.append(cand)
        if cand != original:
            logger.info(f"✅ Tarjima: '{original}' → '{cand}'")
    return out


async def extract_plans_from_text(text: str) -> list[dict]:
    try:
        # O'zbekiston vaqti
        now = datetime.now(TIMEZONE)
        current_time = now.strftime("%H:%M")
        current_date = now.strftime("%d.%m.%Y")

        tomorrow = now + timedelta(days=1)
        tomorrow_date = tomorrow.strftime("%d.%m.%Y")

        logger.info(f"📝 GPT ga yuborilmoqda: '{text}' | Tashkent: {current_time}")

        system_prompt = """Sen professional reja tahlilchi va tarjimonsiz.

ASOSIY VAZIFA: Foydalanuvchi nima demoqchi bo'lsa - aniq tushunib, o'zbek tilida reja chiqarish.

QOIDALAR:
1. title FAQAT O'ZBEK TILIDA lotin harflarida
2. Har bir so'zni diqqat bilan tahlil qil
3. Sonlar va miqdorlar muhim — ularni saqla
4. Faqat JSON formatda javob ber"""

        user_prompt = f"""HOZIRGI VAQT VA SANA:
Tashkent vaqti: {current_time}
Bugungi sana: {current_date}
Ertaga: {tomorrow_date}

FOYDALANUVCHI MATNI:
"{text}"

━━━━━━━━━━━━━━━━━━━━━━━━━━━━

TAHLIL QOIDALARI:

1. SONLAR VA MIQDORLAR:
   Agar son aytilgan bo'lsa — title ga qo'sh!

   MISOLLAR:
   ✅ "10 ta turnik" → "Turnikda 10 ta tortish"
   ✅ "5 km yugurish" → "5 km yugurish"
   ✅ "3 sahifa kitob" → "3 sahifa kitob o'qish"
   ✅ "20 minutlik meditatsiya" → "20 daqiqa meditatsiya"
   ❌ "turnik" → "Turnik mashqi" (son yo'q bo'lsa umumiy)

2. VAQT HISOBLASH:
   Aniq soat:
   - "17:00 da" → "17:00"
   - "soat 9 da" → "09:00"
   - "14:30 da" → "14:30"

   Nisbiy vaqt (hozirgi vaqt: {current_time}):
   - "10 minutdan keyin" → "{(now + timedelta(minutes=10)).strftime("%H:%M")}"
   - "yarim soatdan so'ng" → "{(now + timedelta(minutes=30)).strftime("%H:%M")}"
   - "1 soatdan keyin" → "{(now + timedelta(hours=1)).strftime("%H:%M")}"
   - "2 soatdan so'ng" → "{(now + timedelta(hours=2)).strftime("%H:%M")}"

   Vaqt yo'q:
   - "kechqurun" → null
   - "ertadan" → null

3. BUGUN vs ERTAGA:
   - "ertaga", "sabah", "tomorrow" → for_tomorrow: true
   - Boshqa holatlarda → for_tomorrow: false

4. MAVZU ANIQLASH:
   SPORT va MASHQ:
   - "turnik", "турник", "pull-up" → "Turnikda tortish"
   - "yugurish", "koşmak", "running" → "Yugurish"
   - "sport", "mashq" → "Sport mashg'uloti"
   - "fitnes", "gym" → "Fitnes mashg'uloti"

   O'QUV:
   - "dars", "dars tayyorlash" → "Darsga tayyorgarlik"
   - "AI fanidan", "matematikadan" → "[Fan nomi] darsi"
   - "imtihon", "exam" → "Imtihonga tayyorgarlik"

   KUNDALIK ISH:
   - "uyg'onish", "turish" → "Uyg'onish"
   - "nonushta", "breakfast" → "Nonushta"
   - "uxlash", "sleep" → "Uxlash"

5. TARJIMA (agar boshqa tilda bo'lsa):
   Turkcha → O'zbekcha:
   - "kalkacağım" → "Uyg'onish"
   - "spor yapacağım" → "Sport qilish"
   - "kitap okuyacağım" → "Kitob o'qish"

   Ruscha → O'zbekcha:
   - "проснуться" → "Uyg'onish"
   - "заниматься спортом" → "Sport qilish"
   - "читать книгу" → "Kitob o'qish"

   Inglizcha → O'zbekcha:
   - "wake up" → "Uyg'onish"
   - "workout" → "Sport mashg'uloti"
   - "read a book" → "Kitob o'qish"

6. SCORE BERISH:
   - Oddiy (suv ichish, yurish): 3
   - O'rtacha (kitob, sport, dars): 5
   - Qiyin (proyekt, katta ish): 8
   - Juda qiyin (erta turish, sovuq dush): 6

━━━━━━━━━━━━━━━━━━━━━━━━━━━━

JAVOB FORMATI (faqat JSON):
{{
  "plans": [
    {{
      "title": "O'ZBEK TILIDA aniq sarlavha (miqdor bilan agar bor bo'lsa)",
      "description": null,
      "scheduled_time": "HH:MM yoki null",
      "score_value": 5,
      "for_tomorrow": false
    }}
  ]
}}

ESLATMA: 
- title doim o'zbek tilida lotin harflarida
- Sonlar va miqdorlar saqlansin
- Aniq va tushunarli bo'lsin
- Agar bir nechta reja bo'lsa — hammasini ajrat

FAQAT JSON QAYTAR, BOSHQA HECH NARSA YOZMA!"""

        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.05,  # Pastroq — aniqroq javob
        )

        content = response.choices[0].message.content.strip()
        logger.info(f"✅ GPT: {content[:300]}")

        # JSON tozalash
        if "```" in content:
            parts = content.split("```")
            if len(parts) >= 2:
                content = parts[1]
                if content.startswith("json"):
                    content = content[4:]
                content = content.strip()

        start = content.find("{")
        end = content.rfind("}") + 1
        if start != -1 and end > start:
            content = content[start:end]

        data = json.loads(content)
        plans = data.get("plans", [])

        # Kirill harflar → O'zbek (lotin). Avval HAR kirill title uchun ALOHIDA
        # GPT chaqiruvi bo'lardi (N ta ketma-ket so'rov). Endi barcha kirill
        # title'lar BITTA chaqiruvda tarjima qilinadi (tarmoq/latensiya tejaladi).
        cyr_idx = [i for i, p in enumerate(plans) if _has_cyrillic(p.get("title", ""))]
        if cyr_idx:
            originals = [plans[i].get("title", "") for i in cyr_idx]
            logger.warning(f"⚠️ Kirill topildi ({len(originals)} ta) — bitta so'rovda tarjima qilamiz")
            translated = await _translate_titles_to_latin(originals)
            for j, i in enumerate(cyr_idx):
                plans[i]["title"] = translated[j]

        logger.info(f"✅ Final rejalar: {plans}")
        return plans

    except json.JSONDecodeError as e:
        logger.error(f"❌ JSON parse xatosi: {e}")
        return []
    except Exception as e:
        logger.error(f"❌ GPT xatosi: {type(e).__name__}: {str(e)}")
        raise e


async def extract_time_only(text: str) -> str | None:
    """Faqat vaqtni chiqaradi (HH:MM formatda yoki None)"""
    try:
        now = datetime.now(TIMEZONE)
        current_time = now.strftime("%H:%M")

        logger.info(f"⏰ Vaqt chiqarish: '{text}' | Hozir: {current_time}")

        system_prompt = """Sen vaqt tahlilchi.

VAZIFA: Foydalanuvchi berilgan matn yoki gapdan FAQAT VAQTNI chiqar.

JAVOB: HH:MM formatda yoki 'null' (agar vaqt yo'q bo'lsa)"""

        user_prompt = f"""Hozirgi vaqti: {current_time}

Foydalanuvchi: "{text}"

QOIDALAR:
1. Aniq vaqt: "17:00" → 17:00
2. "soat 9 da" → 09:00
3. "10 minutdan keyin" → {(now + timedelta(minutes=10)).strftime('%H:%M')}
4. "yarim soatdan so'ng" → {(now + timedelta(minutes=30)).strftime('%H:%M')}
5. "1 soatdan keyin" → {(now + timedelta(hours=1)).strftime('%H:%M')}
6. "2 soatdan so'ng" → {(now + timedelta(hours=2)).strftime('%H:%M')}
7. Agar vaqt yo'q bo'lsa → null

FAQAT VAQTNI JAVOB QIL, MASALAN: 17:30 yoki null"""

        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.05,
        )

        result = response.choices[0].message.content.strip()
        logger.info(f"✅ Extracted time: '{result}'")

        # Vaqt formatini tekshirish (HH:MM)
        if result and result != "null" and ":" in result:
            parts = result.split(":")
            if len(parts) == 2:
                try:
                    hour = int(parts[0])
                    minute = int(parts[1])
                    if 0 <= hour <= 23 and 0 <= minute <= 59:
                        return f"{hour:02d}:{minute:02d}"
                except ValueError:
                    pass

        return None

    except Exception as e:
        logger.error(f"❌ Vaqt chiqarish xatosi: {type(e).__name__}: {str(e)}")
        return None



# ─────────────────────────────────────────────────────────────
#  AI COACH — suhbat (chat) rejimi
# ─────────────────────────────────────────────────────────────
COACH_PERSONA = """Sen — "Intizom AI": 10 yillik tajribaga ega shaxsiy psixolog, motivator va intizom murabbiysisan. O'zbek tilida (lotin) gaplashasan.

ICHKI BILIM (foydalanuvchiga aytma):
- Suhbat boshida foydalanuvchining maqsadlari, oxirgi 7 kunlik rejalari, streak, daraja va kayfiyat tarixi senga beriladi.
- Javob berishdan OLDIN bu ma'lumotni ichingda chuqur tahlil qil: izchillik (consistency), kuchli/zaif tomonlar, kayfiyat va energiya tendensiyasi, qaysi maqsadlar turg'un qolgan.
- Bu tahlilni shunchaki ichki ravishda ishlat — javobing tabiiy, jonli va aniq bo'lsin.

ASOSIY QOIDA — ORTIQCHA GAPIRMA:
- Foydalanuvchi SAVOL bermaguncha "men sen haqingda shularni bilaman", "ma'lumotlaringni ko'rib turibman", "rejalaring shular" kabi hisobot BERMA.
- Foydalanuvchi shunchaki "salom" desa — iliq salomlash va qisqa, tabiiy savol ber (masalan: "Salom! Bugun nima ustida ishlaymiz?"). Ma'lumotlarini sanab chiqma.
- Faqat foydalanuvchi o'zi so'raganda (masalan "men haqimda nima bilasan?", "rejalarimni tahlil qil") — o'shanda ma'lumotlaridan aniq misol va raqamlar bilan javob ber.
- Aks holda: shunchaki uning savoliga to'g'ridan-to'g'ri, foydali javob ber. Ma'lumotlardan faqat javobni shaxsiylashtirish uchun, kerak bo'lganda, sezdirmasdan foydalan.

USLUB:
- Iliq, qo'llab-quvvatlovchi, dono. Hech qachon uyaltirmaysan, ayblamaysan, "toxic" bo'lmaysan.
- Qisqa va aniq: 2-5 jumla. 1-2 ta mos emoji. Kerak bo'lsa bitta amaliy keyingi qadam.
- Faqat o'zbek tilida (lotin). Foydalanuvchiga "sen" deb murojaat qil.
- HECH QACHON "men ma'lumotingizni ko'rmayman / ma'lumot yo'q" dema."""


async def chat_with_coach(context_block: str, history: list[dict]) -> str:
    """
    AI Coach bilan suhbat. `history` — [{role, content}, ...] (ephemeral,
    saqlanmaydi). `context_block` — foydalanuvchining maqsad/reja/statistikasi.
    """
    if not OPENAI_API_KEY:
        logger.error("❌ OPENAI_API_KEY topilmadi (bo'sh). .env da OPENAI_API_KEY ni tekshiring.")
        return (
            "⚙️ AI hozircha sozlanmagan (API kalit topilmadi). "
            "Administrator bilan bog'laning."
        )
    try:
        # Tarix (oxirgi 12 ta xabar)
        convo = []
        for m in history[-12:]:
            role = m.get("role")
            content = (m.get("content") or "").strip()
            if role in ("user", "assistant") and content:
                convo.append({"role": role, "content": content[:1500]})

        if not convo:
            return "Salom! Men Intizom AI murabbiyingman 🌱 Bugun nima ustida ishlaymiz?"

        messages = [{"role": "system", "content": COACH_PERSONA}]

        # Kontekst (foydalanuvchining REAL maqsad/reja/kayfiyati) HAR safar
        # ALOHIDA system xabar sifatida beriladi. Bu modelning ma'lumotni
        # "o'ylab topishini" (hallucination) oldini oladi — u har doim faqat
        # haqiqiy ma'lumotga tayanadi. Persona qoidasi bo'yicha so'ralmaguncha
        # uni sanab bermaydi, lekin javobni shu real ma'lumotga asoslaydi.
        if context_block:
            messages.append({
                "role": "system",
                "content": (
                    "FOYDALANUVCHINING REAL HOLATI (faqat shu ma'lumotga tayan, "
                    "hech narsa o'ylab topma). Foydalanuvchi rejalari/maqsadlari "
                    "haqida so'rasa — AYNAN shu yerdan o'qib ayt, boshqa narsa "
                    "to'qib chiqarma. So'ramasa — sanab berma, lekin javobni shu "
                    "holatga moslab ber:\n" + context_block
                ),
            })

        messages.extend(convo)

        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            temperature=0.4,
            max_tokens=450,
        )
        reply = (response.choices[0].message.content or "").strip()
        return reply or "Hmm, hozir javob topa olmadim. Yana bir bor yozib ko'rasanmi?"

    except Exception as e:
        # Aniq sababni log'ga yozamiz (deploy debug uchun)
        logger.error(
            f"❌ AI Coach chat xatosi: {type(e).__name__}: {e}", exc_info=True
        )
        return (
            "⚠️ Hozir AI bilan bog'lanishda kichik nosozlik bo'ldi. "
            "Bir oz kutib, qaytadan urinib ko'r."
        )
