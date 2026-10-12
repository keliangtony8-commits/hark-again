"""通用 CRUD 路由工厂。简单资源（项目、记忆、定时任务）都用它生成，
特殊逻辑写在各自的路由文件里，避免每个资源复制一套增删改查。"""
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import require_user
from ..db import Base, get_session
from ..wire_time import wire


def _dump(obj: Base) -> dict[str, Any]:
    """列上标了 info={"private": True} 的（向量、密文等）不出接口。"""
    out = {}
    for c in obj.__table__.columns:
        if c.info.get("private"):
            continue
        v = getattr(obj, c.name)
        out[c.name] = wire(v)
    return out


def crud_router(prefix: str, model: type[Base], create: type[BaseModel], update: type[BaseModel],
                order_by=None,
                on_delete: Callable[[AsyncSession, Any], Awaitable[None]] | None = None,
                extra: Callable[[Any], dict[str, Any]] | None = None,
                annotate: Callable[[AsyncSession, list[Any]], Awaitable[dict[str, dict[str, Any]]]] | None = None,
                on_update: Callable[[Any, dict[str, Any]], None] | None = None,
                after_update: Callable[[AsyncSession, Any, dict[str, Any]], Awaitable[None]] | None = None) -> APIRouter:
    """on_delete：删除前的级联清理钩子（如删项目时删其对话）。
    extra：给每条记录补上算出来的只读字段（不存库，如任务的 next_run_at），所有接口一致带上。
    annotate：同样是只读字段，但要查库（如项目的对话数）：一次拿一批记录，返回 {id: 字段}，列表接口只多一条聚合查询。
    on_update：PATCH 写库前的钩子 (obj, changes)，负责派生字段（如项目档案的“谁改的/何时改的”）或抛 HTTPException 拒绝。
    after_update：字段写上之后、commit 之前的异步钩子 (db, obj, changes)，同步别的表里的镜像字段（如面板改名 → 卡片标题）。"""
    r = APIRouter(prefix=prefix, dependencies=[Depends(require_user)])

    def _iso(d: dict[str, Any]) -> dict[str, Any]:
        return {k: wire(v) for k, v in d.items()}

    async def out_many(db: AsyncSession, objs: list[Base]) -> list[dict[str, Any]]:
        more = await annotate(db, objs) if annotate and objs else {}
        rows = []
        for obj in objs:
            d = _dump(obj)
            if extra:
                d.update(_iso(extra(obj)))
            d.update(_iso(more.get(obj.id, {})))
            rows.append(d)
        return rows

    async def out(db: AsyncSession, obj: Base) -> dict[str, Any]:
        return (await out_many(db, [obj]))[0]

    @r.get("")
    async def list_items(db: AsyncSession = Depends(get_session)):
        q = select(model)
        if order_by is not None:
            q = q.order_by(order_by)
        return await out_many(db, list((await db.scalars(q)).all()))

    @r.post("")
    async def create_item(body: create, db: AsyncSession = Depends(get_session)):  # type: ignore[valid-type]
        obj = model(**body.model_dump())
        db.add(obj)
        await db.commit()
        return await out(db, obj)

    @r.get("/{item_id}")
    async def get_item(item_id: str, db: AsyncSession = Depends(get_session)):
        obj = await db.get(model, item_id)
        if not obj:
            raise HTTPException(404)
        return await out(db, obj)

    @r.patch("/{item_id}")
    async def update_item(item_id: str, body: update, db: AsyncSession = Depends(get_session)):  # type: ignore[valid-type]
        obj = await db.get(model, item_id)
        if not obj:
            raise HTTPException(404)
        changes = body.model_dump(exclude_unset=True)
        if on_update:
            on_update(obj, changes)
        for k, v in changes.items():
            setattr(obj, k, v)
        if after_update:
            await after_update(db, obj, changes)
        await db.commit()
        return await out(db, obj)

    @r.delete("/{item_id}")
    async def delete_item(item_id: str, db: AsyncSession = Depends(get_session)):
        if obj := await db.get(model, item_id):
            if on_delete:
                await on_delete(db, obj)
            await db.delete(obj)
            await db.commit()
        return {"ok": True}

    return r
