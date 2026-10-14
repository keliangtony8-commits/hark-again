"""钱包接口（v2.74）：列（只有名字 / 卡组织 / 尾号 / 有效期）、加、改名、删。没有任何返回卡号或安全码的接口。规则在 app/wallet.py。"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from .. import wallet
from ..auth import require_user
from ..db import get_session
from ..models import PaymentCard

router = APIRouter(prefix="/api/wallet", dependencies=[Depends(require_user)])


class CardIn(BaseModel):
    number: str
    exp_month: int | str
    exp_year: int | str
    cvc: str
    label: str = ""
    holder: str = ""
    postal_code: str = ""


class CardPatch(BaseModel):
    label: str


@router.get("")
async def list_cards(db: AsyncSession = Depends(get_session)):
    return [wallet.public(c) for c in await wallet.cards(db)]


@router.post("")
async def add_card(body: CardIn, db: AsyncSession = Depends(get_session)):
    try:
        card = await wallet.add(db, body.number, body.exp_month, body.exp_year, body.cvc, body.label, body.holder, body.postal_code)
    except wallet.CardError as e:
        raise HTTPException(409 if e.kind == "dupe" else 400, str(e))
    except RuntimeError as e:  # 没配 VAULT_KEY
        raise HTTPException(503, str(e))
    await db.commit()
    return wallet.public(card)


@router.patch("/{card_id}")
async def rename_card(card_id: str, body: CardPatch, db: AsyncSession = Depends(get_session)):
    card = await db.get(PaymentCard, card_id)
    if not card:
        raise HTTPException(404, "没有这张卡")
    try:
        wallet.rename(card, body.label)
    except wallet.CardError as e:
        raise HTTPException(400, str(e))
    await db.commit()
    return wallet.public(card)


@router.delete("/{card_id}")
async def delete_card(card_id: str, db: AsyncSession = Depends(get_session)):
    card = await db.get(PaymentCard, card_id)
    if not card:
        raise HTTPException(404, "没有这张卡")
    await db.delete(card)
    await db.commit()
    return {"ok": True}
