"""沙盒执行器：唯一接触 Docker 的服务。

- 每个项目一个长驻容器 sbx-<project_id>，工作目录挂载 data/projects/<id>
- 资源限制：内存、CPU、进程数；去掉所有 Linux capability；禁止提权
- 单条命令超时即杀；输出截断
- 空闲超过 IDLE_MINUTES 的容器自动停止，省 VPS 内存
后端只能通过带 token 的 HTTP 调它，模型永远碰不到 Docker 本身。
"""
import asyncio
import os
import re
import time

import docker
from docker.errors import NotFound
from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel

TOKEN = os.environ["SANDBOX_TOKEN"]
HOST_PROJECTS = os.environ["HOST_PROJECTS_DIR"]  # 宿主机上的绝对路径（Docker 挂载要用）
IMAGE = os.environ.get("SANDBOX_IMAGE", "assistant-sandbox:latest")
MEM = os.environ.get("SANDBOX_MEM", "1g")
CPUS = float(os.environ.get("SANDBOX_CPUS", "1"))
IDLE_MINUTES = int(os.environ.get("SANDBOX_IDLE_MINUTES", "30"))
MAX_OUTPUT = 12000

client = docker.from_env()
last_used: dict[str, float] = {}
app = FastAPI()


def auth(authorization: str = Header("")) -> None:
    if authorization != f"Bearer {TOKEN}":
        raise HTTPException(401)


class ExecIn(BaseModel):
    project_id: str
    command: str
    timeout: int = 60


def _container(pid: str):
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", pid):
        raise HTTPException(400, "bad project id")
    name = f"sbx-{pid}"
    try:
        c = client.containers.get(name)
        if c.status != "running":
            c.start()
        return c
    except NotFound:
        host_dir = os.path.join(HOST_PROJECTS, pid)
        os.makedirs(f"/projects/{pid}", exist_ok=True)
        os.chown(f"/projects/{pid}", 1000, 1000)
        return client.containers.run(
            IMAGE, name=name, detach=True, working_dir="/workspace",
            volumes={host_dir: {"bind": "/workspace", "mode": "rw"}},
            mem_limit=MEM, nano_cpus=int(CPUS * 1e9), pids_limit=256,
            cap_drop=["ALL"], security_opt=["no-new-privileges"],
            labels={"assistant.sandbox": "1"},
        )


def _exec(pid: str, command: str, timeout: int) -> dict:
    c = _container(pid)
    last_used[pid] = time.time()
    # coreutils timeout 负责杀超时进程；-k 再给 5 秒强杀
    res = c.exec_run(["timeout", "-k", "5", str(timeout), "bash", "-lc", command], workdir="/workspace", demux=False)
    out = (res.output or b"").decode("utf-8", "replace")
    if len(out) > MAX_OUTPUT:
        out = out[:MAX_OUTPUT // 2] + "\n…（中间省略）…\n" + out[-MAX_OUTPUT // 2:]
    return {"exit_code": res.exit_code, "timed_out": res.exit_code == 124, "output": out}


@app.post("/exec", dependencies=[Depends(auth)])
async def exec_(body: ExecIn):
    return await asyncio.to_thread(_exec, body.project_id, body.command, max(1, min(body.timeout, 120)))


@app.delete("/sandboxes/{pid}", dependencies=[Depends(auth)])
async def remove(pid: str):
    try:
        client.containers.get(f"sbx-{pid}").remove(force=True)
    except NotFound:
        pass
    return {"ok": True}


async def _reaper():
    while True:
        await asyncio.sleep(60)
        now = time.time()
        for pid, t in list(last_used.items()):
            if now - t > IDLE_MINUTES * 60:
                try:
                    await asyncio.to_thread(client.containers.get(f"sbx-{pid}").stop, timeout=5)
                except NotFound:
                    pass
                last_used.pop(pid, None)


@app.on_event("startup")
async def _start():
    asyncio.create_task(_reaper())
