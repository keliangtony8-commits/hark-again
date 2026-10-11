"""目录接口：可选模型、技能库。技能读写都在 skills_store.py，这里只做收发。（连接器在 routes/connectors.py）"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import llm, skills_store
from ..auth import require_user

router = APIRouter(prefix="/api/catalog", dependencies=[Depends(require_user)])

class SkillIn(BaseModel):
    name: str
    description: str
    body: str = ""


@router.get("/models")
async def models():
    """聊天可选的模型（别名 + 显示名）和默认别名；客户端据此画输入框上的切换。"""
    return llm.chat_models()


def _skill_op(fn, *args):
    """skills_store 的错误统一翻成 HTTP：KeyError → 404，ValueError → 400。"""
    try:
        return fn(*args)
    except KeyError:
        raise HTTPException(404, "没有这个技能")
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/skills")
async def skills():
    return [s.dict() for s in skills_store.list_skills()]


@router.post("/skills")
async def create_skill(body: SkillIn):
    return skills_store.save_skill(body.name, body.description, body.body).dict()


@router.put("/skills/{sid}")
async def update_skill(sid: str, body: SkillIn):
    return _skill_op(skills_store.save_skill, body.name, body.description, body.body, sid).dict()


@router.post("/skills/{sid}/customize")
async def customize_skill(sid: str):
    """内置 → 复制一份可改的自定义版（同 id，顶替内置）。"""
    return _skill_op(skills_store.customize, sid).dict()


@router.post("/skills/{sid}/reset")
async def reset_skill(sid: str):
    """自定义版 → 恢复内置原样。"""
    return _skill_op(skills_store.reset, sid).dict()


@router.post("/skills/{sid}/enable")
async def enable_skill(sid: str):
    return _skill_op(skills_store.set_enabled, sid, True).dict()


@router.post("/skills/{sid}/disable")
async def disable_skill(sid: str):
    """停用：留在库里，但模型看不到、用不了。"""
    return _skill_op(skills_store.set_enabled, sid, False).dict()


@router.delete("/skills/{sid}")
async def delete_skill(sid: str):
    _skill_op(skills_store.delete_skill, sid)
    return {"ok": True}
