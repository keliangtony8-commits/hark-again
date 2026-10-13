"""Home 卡片的动作接口：建议卡的主按钮（规则在 app/home_offers.py）、面板的移除 / 找回（规则在 app/panel_trash.py）。
CRUD 本身仍是 resources 里的 /api/cards。"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from .. import home_offers, panel_trash
from ..auth import require_user
from ..db import get_session
from ..models import HomeCard

router = APIRouter(prefix="/api/cards", tags=["home"], dependencies=[Depends(require_user)])


@router.post("/{card_id}/start")
async def start_offer(card_id: str, db: AsyncSession = Depends(get_session)):
    """点建议卡的主按钮 → {conversation_id, prompt, started}。started=True 时客户端把 prompt 发进这段新对话。"""
    try:
        card, started = await home_offers.start(db, card_id)
    except LookupError:
        raise HTTPException(404, "这张建议卡不在了")
    return {"conversation_id": card.conversation_id, "prompt": card.action_prompt, "started": started}


@router.post("/{card_id}/remove")
async def remove_panel(card_id: str, db: AsyncSession = Depends(get_session)):
    """把面板从 Home 拿掉：停止刷新，30 天内可找回 → {id, title, revivable}。不是面板 422。"""
    card = await db.get(HomeCard, card_id)
    if card is None:
        raise HTTPException(404, "这张卡不在了")
    try:
        card = await panel_trash.remove(db, card)
    except ValueError as e:
        raise HTTPException(422, str(e))
    return {"id": card.id, "title": card.title, "revivable": panel_trash.revivable(card)}


@router.post("/{card_id}/revive")
async def revive_panel(card_id: str, db: AsyncSession = Depends(get_session)):
    """找回最近移除的面板 → {id, title, task_id}；它会马上重新取一次数据。找不回 404（带原因）。"""
    try:
        card, task = await panel_trash.revive(db, card_id)
    except LookupError as e:
        raise HTTPException(404, str(e))
    return {"id": card.id, "title": card.title, "task_id": task.id}
