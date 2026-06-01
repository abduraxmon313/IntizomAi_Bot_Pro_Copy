#!/usr/bin/env python3
"""
WLCM onboarding — BIR MARTALIK skript.

Onboarding token (PROD_TOKEN) yordamida partner uchun `api_key` + `api_secret`
oladi va ularni ekranga chiqaradi. Keyin shu kalitlarni `.env` (lokal) yoki
Railway env'ga `API_KEY` / `API_SECRET` sifatida qo'yasiz.

⚠️  Token cheklangan martalik (uses_left). Shu sabab bu skriptni FAQAT BIR MARTA
    ishlating, olingan kalitlarni saqlab qo'ying va boshqa qayta chaqirmang.

ISHLATISH:
    # .env da PROD_TOKEN (va Base_URL) to'ldirilgan bo'lsa:
    python onboard.py

    # yoki to'g'ridan-to'g'ri:
    python onboard.py --token <ONBOARDING_TOKEN> --name intizom-ai-prod

    # faqat tokenni tekshirish (kalit olmasdan):
    python onboard.py --check
"""
import argparse
import asyncio
import sys

from bot.config import PAYLOV_BASE_URL, PAYLOV_PROD_TOKEN, PAYLOV_PARTNER_ID
from bot.services.onboarding import (
    OnboardingError,
    complete_onboarding,
    validate_token,
)


def _print_header() -> None:
    print("=" * 60)
    print("  WLCM ONBOARDING — api_key + api_secret olish")
    print("=" * 60)
    print(f"  Base URL   : {PAYLOV_BASE_URL}")
    print(f"  Partner ID : {PAYLOV_PARTNER_ID or '(berilmagan)'}")
    tok = PAYLOV_PROD_TOKEN or ""
    masked = (tok[:6] + "…" + tok[-4:]) if len(tok) > 12 else ("(yo'q)" if not tok else "***")
    print(f"  Token      : {masked}")
    print("-" * 60)


async def _run(args: argparse.Namespace) -> int:
    _print_header()

    token = args.token or PAYLOV_PROD_TOKEN
    if not token:
        print("❌ Token yo'q. .env da PROD_TOKEN ni to'ldiring yoki --token bering.")
        return 1

    # 1) Tokenni tekshiramiz (uses_left ni kamaytirmaydi).
    try:
        path, info = await validate_token(token)
    except OnboardingError as e:
        print(f"❌ Token tekshiruvi muvaffaqiyatsiz:\n   {e}")
        return 1

    print(f"✅ Token valid. Endpoint: {path}")
    if info:
        print(f"   Javob: {info}")

    if args.check:
        print("\nℹ️  --check rejimi: kalit olinmadi (token saqlanib qoldi).")
        return 0

    # 2) Onboarding'ni yakunlab, kalitlarni olamiz (uses_left kamayadi).
    print(f"\n🔑 API key yaratilmoqda (name='{args.name}')...")
    try:
        data = await complete_onboarding(args.name, token=token, path=path)
    except OnboardingError as e:
        print(f"❌ Onboarding muvaffaqiyatsiz:\n   {e}")
        return 1

    api_key = data.get("api_key", "")
    api_secret = data.get("api_secret", "")

    print("\n" + "=" * 60)
    print("  ✅ MUVAFFAQIYATLI! Quyidagilarni .env / Railway env ga qo'ying:")
    print("=" * 60)
    print(f"API_KEY={api_key}")
    print(f"API_SECRET={api_secret}")
    print("=" * 60)
    print("\n⚠️  Bu kalitlarni XAVFSIZ saqlang. api_secret QAYTA ko'rsatilmaydi.")
    print("    Token sarflandi — bu skriptni qayta ishlatish shart emas.")
    print("\n  Keyingi qadam: API_KEY/API_SECRET ni env ga qo'ygach,")
    print("  PAYLOV_ENABLED avtomatik True bo'ladi va haqiqiy to'lov ishlaydi.")
    print("  Tekshirish:  python -c \"import asyncio; from bot.services.paylov "
          "import get_me; print(asyncio.run(get_me()))\"")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="WLCM partner onboarding (bir martalik).")
    parser.add_argument("--token", help="Onboarding token (default: .env PROD_TOKEN)")
    parser.add_argument("--name", default="intizom-ai-prod",
                        help="Yaratiladigan API key nomi (default: intizom-ai-prod)")
    parser.add_argument("--check", action="store_true",
                        help="Faqat tokenni tekshirish (kalit olmasdan)")
    args = parser.parse_args()

    try:
        rc = asyncio.run(_run(args))
    except KeyboardInterrupt:
        rc = 130
    sys.exit(rc)


if __name__ == "__main__":
    main()
