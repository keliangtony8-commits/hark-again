"""沙盒执行器：唯一接触 Docker 的服务。

- 每个项目一个长驻容器 sbx-<project_id>，工作目录挂载 data/projects/<id>
- 资源限制：内存、CPU、进程数；去掉所有 Linux capability；禁止提权
- 单条命令超时即杀；输出截断
- 空闲超过 IDLE_MINUTES 的容器自动停止，省 VPS 内存（有后台任务在跑的不停）
- 后台任务（/jobs/*）：后端把 .jobs/<id>/run.sh 写进工作区（脚本约定见 backend/app/jobs.py），
  这里只负责 setsid 脱离启动、查活、整组杀掉；日志和退出码都落在工作区文件里，
  所以这个服务或后端重启都不丢任务状态
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


class JobIn(BaseModel):
    project_id: str
    job_id: str


def _check_job(jid: str) -> str:
    if not re.fullmatch(r"j[0-9a-f]{6,30}", jid):
        raise HTTPException(400, "bad job id")
    return jid


def _existing(pid: str):
    """只找、不启动：查活/取消不该为一个早已停掉的容器把它拉起来。"""
    try:
        c = client.containers.get(f"sbx-{pid}")
    except NotFound:
        return None
    return c if c.status == "running" else None


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


@app.post("/jobs/start", dependencies=[Depends(auth)])
async def job_start(body: JobIn):
    jid = _check_job(body.job_id)

    def go():
        c = _container(body.project_id)
        last_used[body.project_id] = time.time()
        if c.exec_run(["test", "-f", f".jobs/{jid}/run.sh"], workdir="/workspace").exit_code != 0:
            raise HTTPException(404, "job script missing")
        c.exec_run(["setsid", "-f", "bash", f".jobs/{jid}/run.sh"], workdir="/workspace", detach=True)
    await asyncio.to_thread(go)
    return {"ok": True}


# 整组杀：run.sh 里 timeout 是进程组组长（pid 文件记的就是它），TERM 给整组，5 秒后还在就 KILL
_KILL = 'p=$(cat .jobs/{jid}/pid 2>/dev/null) || exit 0; kill -TERM -- -$p 2>/dev/null; ' \
        'for i in 1 2 3 4 5; do kill -0 $p 2>/dev/null || exit 0; sleep 1; done; kill -KILL -- -$p 2>/dev/null; exit 0'


@app.post("/jobs/cancel", dependencies=[Depends(auth)])
async def job_cancel(body: JobIn):
    jid = _check_job(body.job_id)

    def go():
        c = _existing(body.project_id)
        if c is not None:
            c.exec_run(["bash", "-c", _KILL.format(jid=jid)], workdir="/workspace")
    await asyncio.to_thread(go)
    return {"ok": True}


@app.post("/jobs/alive", dependencies=[Depends(auth)])
async def job_alive(body: JobIn):
    jid = _check_job(body.job_id)

    def go() -> bool:
        c = _existing(body.project_id)
        if c is None:
            return False  # 容器停了/没了：里面的进程肯定也没了
        cmd = f'p=$(cat .jobs/{jid}/pid 2>/dev/null) || exit 2; kill -0 $p 2>/dev/null'
        code = c.exec_run(["bash", "-c", cmd], workdir="/workspace").exit_code
        return code == 0 or code == 2 and time.time() - last_used.get(body.project_id, 0) < 30  # 刚启动还没写 pid
    return {"alive": await asyncio.to_thread(go)}


_BUSY = 'for f in .jobs/*/pid; do [ -e "$f" ] || continue; d=${f%/pid}; [ -e "$d/exit" ] && continue; ' \
        'kill -0 "$(cat "$f")" 2>/dev/null && { echo busy; exit 0; }; done; exit 0'


def _busy(pid: str) -> bool:
    c = _existing(pid)
    if c is None:
        return False
    return b"busy" in (c.exec_run(["bash", "-c", _BUSY], workdir="/workspace").output or b"")


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
                if await asyncio.to_thread(_busy, pid):  # 后台任务还在跑：算它在用
                    last_used[pid] = now
                    continue
                try:
                    await asyncio.to_thread(client.containers.get(f"sbx-{pid}").stop, timeout=5)
                except NotFound:
                    pass
                last_used.pop(pid, None)


def _adopt() -> None:
    """服务重启后 last_used 是空的：把还在跑的沙盒容器认领回来，否则它们永远不会被回收。"""
    for c in client.containers.list(filters={"label": "assistant.sandbox=1"}):
        if c.name.startswith("sbx-"):
            last_used.setdefault(c.name[4:], time.time())


@app.on_event("startup")
async def _start():
    await asyncio.to_thread(_adopt)
    asyncio.create_task(_reaper())
