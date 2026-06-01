"""
Paylov / wlcm.uz Integration API klienti.

HMAC-SHA256 imzo (docs bo'yicha):
  canonical_path = path (+ ?sorted_urlencoded_query bo'lsa)
  body_hash      = SHA256(raw_body_bytes).hexdigest()
  message        = "{METHOD}\\n{canonical_path}\\n{TIMESTAMP_MS}\\n{body_hash}"
  signature      = HMAC_SHA256(key=API_SECRET, msg=message).hexdigest()

Headerlar: X-API-Key, X-Timestamp (unix millisekund), X-Signature, Content-Type.

MUHIM: imzo aynan YUBORILGAN raw body baytlari asosida hisoblanadi. Shu sabab
body bir marta JSON-string (bytes) ga aylantiriladi va xuddi shu baytlar ham
yuboriladi, ham imzolanadi.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from urllib.parse import parse_qsl, urlencode

import httpx

from bot.config import (
    PAYLOV_API_KEY,
    PAYLOV_API_SECRET,
    PAYLOV_BASE_URL,
    PAYLOV_PROVIDER,
    PAYLOV_RETURN_URL,
)

logger = logging.getLogger(__name__)

API_PREFIX = "/api/v1"
_TIMEOUT = httpx.Timeout(30.0)


class PaylovError(Exception):
    """Paylov API xatosi."""


def _canonical_path(path: str, query_string: str = "") -> str:
    params = sorted(parse_qsl(query_string, keep_blank_values=True))
    encoded = urlencode(params)
    return f"{path}?{encoded}" if encoded else path


def make_signature(method: str, path: str, timestamp: str, body: bytes,
                   query_string: str = "") -> str:
    """HMAC-SHA256 imzo (raw secret kalit bilan)."""
    canonical_path = _canonical_path(path, query_string)
    body_hash = hashlib.sha256(body).hexdigest()
    message = f"{method.upper()}\n{canonical_path}\n{timestamp}\n{body_hash}"
    return hmac.new(
        PAYLOV_API_SECRET.encode(),
        message.encode(),
        hashlib.sha256,
    ).hexdigest()


def _serialize(payload: dict | None) -> bytes:
    if payload is None:
        return b""
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode()


async def _request(method: str, path: str, payload: dict | None = None) -> dict:
    """Imzolangan so'rov yuboradi va JSON javobni qaytaradi."""
    if not PAYLOV_API_KEY or not PAYLOV_API_SECRET:
        raise PaylovError("Paylov kalitlari sozlanmagan (API_KEY/API_SECRET).")

    body = _serialize(payload)
    timestamp = str(int(time.time() * 1000))
    signature = make_signature(method, path, timestamp, body)

    headers = {
        "X-API-Key": PAYLOV_API_KEY,
        "X-Timestamp": timestamp,
        "X-Signature": signature,
        "Content-Type": "application/json",
    }
    url = f"{PAYLOV_BASE_URL}{path}"

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.request(
                method.upper(), url,
                content=body if body else None,
                headers=headers,
            )
    except httpx.HTTPError as e:
        logger.error(f"❌ Paylov ulanish xatosi {path}: {e}")
        raise PaylovError(f"Ulanish xatosi: {e}") from e

    if resp.status_code >= 400:
        logger.error(f"❌ Paylov {method} {path} → {resp.status_code}: {resp.text[:400]}")
        raise PaylovError(f"Paylov {resp.status_code}: {resp.text[:200]}")

    try:
        return resp.json()
    except Exception:
        return {}


# ─────────────────────────────────────────────────────────────
#  PUBLIC API
# ─────────────────────────────────────────────────────────────
async def get_me() -> dict:
    """Partner ma'lumotlari — kalitlarni tekshirish uchun (debug)."""
    return await _request("GET", f"{API_PREFIX}/integrations/me")


async def create_checkout(external_id: str, amount_tiyin: int,
                          return_url: str | None = None,
                          provider: str | None = None) -> dict:
    """
    Checkout yaratadi.
    amount_tiyin — TIYINDA (so'm * 100). Javob: {order_id, checkout_url, ...}
    """
    payload = {
        "external_id": external_id,
        "amount": int(amount_tiyin),
        "payment_provider": (provider or PAYLOV_PROVIDER),
        "return_url": return_url or PAYLOV_RETURN_URL,
    }
    return await _request("POST", f"{API_PREFIX}/integrations/checkout", payload)


async def register_fiscalization(payment_id, items: list[dict]) -> dict:
    """Soliq cheki (fiscal receipt) yaratadi. items — [{title, price, count, vat_percent}]."""
    payload = {"payment_id": payment_id, "items": items}
    return await _request("POST", f"{API_PREFIX}/fiscalization/register", payload)
