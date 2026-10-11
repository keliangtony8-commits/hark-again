"""Alembic 迁移环境：连接串取自应用配置，表结构取自 models。
改了 models.py 之后：alembic revision --autogenerate -m "说明"，再提交生成的文件。"""
import asyncio

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

from app import models  # noqa: F401  注册所有表
from app.config import settings
from app.db import Base

target_metadata = Base.metadata


def _run(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


async def main() -> None:
    engine = create_async_engine(settings.database_url)
    async with engine.connect() as conn:
        await conn.run_sync(_run)
    await engine.dispose()


asyncio.run(main())
