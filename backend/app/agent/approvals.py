"""等用户答复的中心：审批卡（批准/拒绝）和表单卡（登录、验证码）都在这里挂起。
WebSocket 收到 approval.reply → resolve()，收到 form.reply → resolve_form()。进程内实现，单用户足够；多实例时换成 Redis。

表单答复里的值（密码、验证码）只经过这里交给工具，不写进卡片、不进消息、不回到模型。"""
import asyncio
from dataclasses import dataclass, field
from typing import Any

TIMEOUT_SECONDS = 600
VALUE_MAX = 512  # 单个表单值的长度上限
_pending: dict[str, asyncio.Future[Any]] = {}


@dataclass
class FormReply:
    values: dict[str, str] = field(default_factory=dict)
    remember: bool = False  # 用户勾了“记住到保险箱”


async def _wait(pid: str, default: Any) -> Any:
    fut: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
    _pending[pid] = fut
    try:
        return await asyncio.wait_for(fut, TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        return default
    finally:
        _pending.pop(pid, None)


async def wait(approval_id: str) -> bool:
    return bool(await _wait(approval_id, False))


async def wait_form(form_id: str, fields: list[str]) -> FormReply | None:
    """等表单答复；None = 用户取消或超时。只收卡片上有的字段。"""
    reply = await _wait(form_id, None)
    if not isinstance(reply, FormReply):
        return None
    return FormReply({k: v for k, v in reply.values.items() if k in fields}, reply.remember)


def _settle(pid: str, value: Any) -> bool:
    fut = _pending.get(pid)
    if fut and not fut.done():
        fut.set_result(value)
        return True
    return False


def resolve(approval_id: str, approved: bool) -> bool:
    return _settle(approval_id, approved)


def resolve_form(form_id: str, values: Any, remember: Any = False) -> bool:
    """values = None（取消）或 {字段: 字符串}；非字符串、超长的值丢掉。"""
    if not isinstance(values, dict):
        return _settle(form_id, None)
    clean = {str(k): v[:VALUE_MAX] for k, v in values.items() if isinstance(v, str)}
    return _settle(form_id, FormReply(clean, bool(remember)))
