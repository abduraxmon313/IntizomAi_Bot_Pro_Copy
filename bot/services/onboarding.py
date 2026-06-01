"""
WLCM partner onboarding klienti.

Onboarding token (PROD_TOKEN) yordamida partner uchun `api_key` + `api_secret`
oladi. Bu **BIR MARTALIK** jarayon — olingan kalitlarni `.env` (yoki Railway env)
ga saqlang va keyin shu kalitlar bilan ishlang. Token cheklangan martalik
(`uses_left` har POST'da kamayadi, 0 bo'lsa token o'ladi), shuning uchun uni
har safar chaqirmang.

Endpointlar (docs.wlcm.uz bo'yicha):
  GET  {ONBOARDING_PATH}?token=<TOKEN>            → {"valid": true}
  POST {ONBOARDING_PATH}?token=<TOKEN>  body:{"name": "..."}
                                                  → {id, name, api_key, api_secret}

MUHIM: Onboarding HMAC imzo TALAB QILMAYDI. Autentifikatsiya faqat `token`
query parametri orqali bo'ladi (chunki bu bosqichda hali api_secret yo'q).
"""
from __future__ import annotations

import logging

import httpx

from bot.config import (
    PAYLOV_BASE_URL,
    PAYLOV_ONBOARDING_PATH,
    PAYLOV_PROD_TOKEN,
)

logger = logging.getLogger(__name__)

_TIMEOUT = httpx.Timeout(30.0)

# Server qaysi aniq path'da onboarding berishini bilmasak — quyidagilarni
# navbatma-navbat sinaymiz (404 bo'lsa keyingisiga o'tamiz). Birinchi navbatda
# config'dagi (yoki env'dagi) path tekshiriladi.
_CANDIDATE_PATHS = [
    PAYLOV_ONBOARDING_PATH,
    "/api/v1/partners/onboarding/",
    "/api/v1/partners/onboarding",
    "/partners/onboarding/",
    "/api/v1/onboarding/",
]


class OnboardingError(Exception):
    """Onboarding jarayonidagi xato."""


def _dedup(paths: list[str]) -> list[str]:
    seen, out = set(), []
    for p in paths:
        if p and p not in seen:
            seen.add(p)
            out.append(p)
    return out


def _resolve_token(token: str | None) -> str:
    tok = (token or PAYLOV_PROD_TOKEN or "").strip()
    if not tok:
        raise OnboardingError(
            "Onboarding token topilmadi. .env da PROD_TOKEN (yoki PAYLOV_PROD_TOKEN) "
            "ni to'ldiring yoki token'ni argument sifatida bering."
        )
    return tok


async def validate_token(token: str | None = None) -> tuple[str, dict]:
    """
    Onboarding tokenni tekshiradi (GET). Bu uses_left ni kamaytirmaydi.

    Qaytaradi: (working_path, response_json). Masalan ("/api/v1/partners/onboarding/", {"valid": true}).
    Xato bo'lsa OnboardingError ko'taradi.
    """
    tok = _resolve_token(token)
    last_error: str | None = None

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        for path in _dedup(_CANDIDATE_PATHS):
            url = f"{PAYLOV_BASE_URL}{path}"
            try:
                resp = await client.get(url, params={"token": tok})
            except httpx.HTTPError as e:
                last_error = f"Ulanish xatosi: {e}"
                continue

            if resp.status_code == 404:
                # Bu path mavjud emas — keyingisini sinaymiz.
                last_error = f"404 ({path})"
                continue

            if resp.status_code == 200:
                logger.info(f"✅ Onboarding path topildi: {path}")
                return path, _safe_json(resp)

            # 400/403 — path to'g'ri, lekin token/IP muammosi. Aniq xabar beramiz.
            raise OnboardingError(_explain(resp))

    raise OnboardingError(
        "Onboarding endpoint topilmadi (barcha path'lar 404). "
        f"WLCM_ONBOARDING_PATH ni to'g'ri qiymatga sozlang. Oxirgi: {last_error}"
    )


async def complete_onboarding(name: str, token: str | None = None,
                              path: str | None = None) -> dict:
    """
    Onboarding'ni yakunlaydi (POST) va api_key + api_secret oladi.

    name  — yaratilayotgan API key nomi (masalan "intizom-ai-prod").
    token — onboarding token (default: config PROD_TOKEN).
    path  — aniq path (default: validate_token topgan/yoki config path).

    Qaytaradi: {"id", "name", "api_key", "api_secret"}.
    Xato bo'lsa OnboardingError ko'taradi.
    """
    tok = _resolve_token(token)
    name = (name or "").strip()
    if not name:
        raise OnboardingError("API key nomi (name) bo'sh bo'lmasligi kerak.")

    # Path berilmagan bo'lsa — avval GET bilan to'g'ri path'ni aniqlaymiz.
    if not path:
        path, _ = await validate_token(tok)

    url = f"{PAYLOV_BASE_URL}{path}"
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        try:
            resp = await client.post(
                url,
                params={"token": tok},
                json={"name": name},
                headers={"Content-Type": "application/json"},
            )
        except httpx.HTTPError as e:
            raise OnboardingError(f"Ulanish xatosi: {e}") from e

    if resp.status_code in (200, 201):
        data = _safe_json(resp)
        if not data.get("api_key") or not data.get("api_secret"):
            raise OnboardingError(
                f"Javobda api_key/api_secret yo'q: {data}"
            )
        return data

    raise OnboardingError(_explain(resp))


def _safe_json(resp: httpx.Response) -> dict:
    try:
        return resp.json()
    except Exception:
        return {}


def _explain(resp: httpx.Response) -> str:
    """HTTP xato kodini hujjatdagi sabablarga moslab tushuntiradi."""
    body = _safe_json(resp)
    code = body.get("code") or ""
    status = resp.status_code

    known = {
        "invalid_or_expired": "Token noto'g'ri yoki muddati tugagan (yoki uses_left=0 / is_used=true).",
        "ip_not_allowed": "IP whitelist mos emas — ruxsat etilgan IP dan murojaat qiling.",
        "partner_inactive": "Partner active emas — WLCM bilan bog'laning.",
        "internal_error": "Server xatosi (500) — birozdan so'ng qayta urinib ko'ring.",
    }
    hint = known.get(code, "")
    text = (resp.text or "")[:300]
    return f"Onboarding xato (HTTP {status}, code={code or '-'}). {hint} Javob: {text}"
