"""
Mobil ilova uchun kirish endpointi.

Ilova bot havolasini ochgandan keyin shu endpointni har 2 soniyada so'raydi.
Foydalanuvchi botda kirishni tasdiqlagach JWT token qaytariladi. Qolgan barcha
so'rovlar mavjud `/api/webapp/*` endpointlari orqali (Bearer token bilan) ketadi,
shuning uchun Mini App va ilova bir xil qoidalar bilan ishlaydi.
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from bot.services.app_auth import consume_login_request, create_app_token, is_valid_nonce
from bot.services.user_service import get_user_by_telegram_id
from database.db import AsyncSessionLocal

router = APIRouter()


class PollIn(BaseModel):
    nonce: str


@router.post("/app-auth/poll")
async def poll_login(body: PollIn):
    if not is_valid_nonce(body.nonce):
        raise HTTPException(status_code=400, detail="Noto'g'ri so'rov")
    async with AsyncSessionLocal() as session:
        status, telegram_id = await consume_login_request(session, body.nonce)
        if status != "approved":
            return {"status": status}
        user = await get_user_by_telegram_id(session, telegram_id)
        if user is None:
            return {"status": "expired"}
    return {"status": "approved", "token": create_app_token(telegram_id)}
