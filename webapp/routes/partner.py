"""
Mobil ilova backend'i uchun partner API: /partner/v1/...

Faqat ilova backend'i chaqiradi (server→server). Har bir so'rov HMAC bilan
imzolanadi (bot/services/partner_service.py). '/api/' ostida emas — IP rate
limit middleware'iga tushmaydi, himoya imzo orqali.
"""
import json
import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from bot.services import partner_service as svc
from database.db import AsyncSessionLocal

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/partner/v1")


async def _auth(request: Request) -> bytes | None:
    body = await request.body()
    path = request.url.path + (f"?{request.url.query}" if request.url.query else "")
    if not svc.verify_request(request.method, path, request.headers, body):
        return None
    return body


def _err(e: svc.PartnerError) -> JSONResponse:
    return JSONResponse(status_code=e.status, content={"detail": e.detail, "code": e.code})


def _unauthorized() -> JSONResponse:
    return JSONResponse(status_code=401, content={"detail": "invalid signature", "code": "unauthorized"})


def _json(body: bytes) -> dict:
    try:
        data = json.loads(body or b"{}")
        return data if isinstance(data, dict) else {}
    except ValueError:
        return {}


@router.get("/plans")
async def plans(request: Request, promo_code: str | None = None):
    if await _auth(request) is None:
        return _unauthorized()
    async with AsyncSessionLocal() as session:
        return await svc.catalog(session, promo_code)


@router.post("/orders")
async def create_order(request: Request):
    body = await _auth(request)
    if body is None:
        return _unauthorized()
    async with AsyncSessionLocal() as session:
        try:
            return await svc.create_order(session, _json(body))
        except svc.PartnerError as e:
            return _err(e)


@router.get("/orders/{external_id}")
async def get_order(external_id: str, request: Request):
    if await _auth(request) is None:
        return _unauthorized()
    async with AsyncSessionLocal() as session:
        try:
            return await svc.get_order(session, external_id)
        except svc.PartnerError as e:
            return _err(e)


@router.post("/promo/redeem")
async def redeem(request: Request):
    body = await _auth(request)
    if body is None:
        return _unauthorized()
    async with AsyncSessionLocal() as session:
        try:
            return await svc.redeem_promo(session, _json(body))
        except svc.PartnerError as e:
            return _err(e)
