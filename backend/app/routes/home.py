"""Home 建议卡的动作接口（规则全在 app/home_offers.py）。CRUD 本身仍是 resources 里的 /api/cards。"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from .. import home_offers
from ..auth import require_user
from ..db import get_session

router = APIRouter(prefix="/api/cards", tags=["home"], dependencies=[Depends(require_user)])


@router.post("/{card_id}/start")
async def start_offer(card_id: str, db: AsyncSession = Depends(get_session)):
    """点建议卡的主按钮 → {conversation_id, prompt, started}。started=True 时客户端把 prompt 发进这段新对话。"""
    try:
        card, started = await home_offers.start(db, card_id)
    except LookupError:
        raise HTTPException(404, "这张建议卡不在了")
    return {"conversation_id": card.conversation_id, "prompt": card.action_prompt, "started": started}
