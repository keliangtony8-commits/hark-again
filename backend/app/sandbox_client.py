"""沙盒执行器客户端。后端不接触 Docker，只通过 HTTP 请求独立的 sandbox 服务。"""
import httpx

from .config import settings


async def run(project_id: str, command: str, timeout: int = 60) -> dict:
    async with httpx.AsyncClient(timeout=timeout + 15) as c:
        r = await c.post(f"{settings.sandbox_url}/exec",
                         headers={"Authorization": f"Bearer {settings.sandbox_token}"},
                         json={"project_id": project_id, "command": command, "timeout": timeout})
        r.raise_for_status()
        return r.json()


async def remove(project_id: str) -> None:
    """删除项目时回收它的容器。沙盒服务不在线也不阻塞删除。"""
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            await c.delete(f"{settings.sandbox_url}/sandboxes/{project_id}",
                           headers={"Authorization": f"Bearer {settings.sandbox_token}"})
    except httpx.HTTPError:
        pass


async def _job(action: str, project_id: str, job_id: str) -> dict:
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(f"{settings.sandbox_url}/jobs/{action}",
                         headers={"Authorization": f"Bearer {settings.sandbox_token}"},
                         json={"project_id": project_id, "job_id": job_id})
        r.raise_for_status()
        return r.json()


async def start_job(project_id: str, job_id: str) -> None:
    """脚本已由 jobs.py 写进工作区 .jobs/<id>/run.sh；这里只叫沙盒脱离启动它。"""
    await _job("start", project_id, job_id)


async def cancel_job(project_id: str, job_id: str) -> None:
    await _job("cancel", project_id, job_id)


async def job_alive(project_id: str, job_id: str) -> bool:
    return bool((await _job("alive", project_id, job_id)).get("alive"))
