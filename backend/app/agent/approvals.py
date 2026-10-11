"""审批中心：高风险工具调用在这里挂起，等用户在审批卡上点“批准/拒绝”。
WebSocket 收到 approval.reply 时调用 resolve()。进程内实现，单用户足够；多实例时换成 Redis。"""
import asyncio

TIMEOUT_SECONDS = 600
_pending: dict[str, asyncio.Future[bool]] = {}


async def wait(approval_id: str) -> bool:
    fut: asyncio.Future[bool] = asyncio.get_running_loop().create_future()
    _pending[approval_id] = fut
    try:
        return await asyncio.wait_for(fut, TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        return False
    finally:
        _pending.pop(approval_id, None)


def resolve(approval_id: str, approved: bool) -> bool:
    fut = _pending.get(approval_id)
    if fut and not fut.done():
        fut.set_result(approved)
        return True
    return False
