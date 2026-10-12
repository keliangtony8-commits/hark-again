"""沙盒执行器：唯一接触 Docker 的服务。

- 每个项目一个长驻容器 sbx-<project_id>，工作目录挂载 data/projects/<id>
- 资源限制：内存、CPU、进程数；去掉所有 Linux capability；禁止提权
- 单条命令超时即杀；/exec/stream 边跑边把新输出推给后端（NDJSON，每 FLUSH_S 秒一批，聊天里实时看），
  后端断开（用户点停止）就整组杀掉；可带 stdin（≤ STDIN_MAX，不带则标准输入为空，交互提示不会卡住）；输出太长时给后端开头 + 结尾，完整输出写进工作区 .spill/（约定见 backend/app/spill.py）
- 容器里的家目录在工作区 .home（镜像 /etc/profile.d/workspace.sh）：pip/npm 用户级安装都落在工作区，
  所以容器可以随时删掉重建——镜像更新后（预装清单变了），旧容器在下次用到时自动换成新镜像（有后台任务在跑的不换）
- 空闲超过 IDLE_MINUTES 的容器自动停止，省 VPS 内存（有后台任务在跑的不停）
- 后台任务（/jobs/*）：后端把 .jobs/<id>/run.sh 写进工作区（脚本约定见 backend/app/jobs.py），
  这里只负责 setsid 脱离启动、查活、整组杀掉；日志和退出码都落在工作区文件里，
  所以这个服务或后端重启都不丢任务状态
后端只能通过带 token 的 HTTP 调它，模型永远碰不到 Docker 本身。
"""
import asyncio
import base64
import codecs
import json
import os
import re
import threading
import time

import docker
from docker.errors import NotFound
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

TOKEN = os.environ["SANDBOX_TOKEN"]
HOST_PROJECTS = os.environ["HOST_PROJECTS_DIR"]  # 宿主机上的绝对路径（Docker 挂载要用）
IMAGE = os.environ.get("SANDBOX_IMAGE", "assistant-sandbox:latest")
MEM = os.environ.get("SANDBOX_MEM", "1g")
CPUS = float(os.environ.get("SANDBOX_CPUS", "1"))
IDLE_MINUTES = int(os.environ.get("SANDBOX_IDLE_MINUTES", "30"))
MAX_OUTPUT = 12000
SPILL_MARK = "\n…（中间省略）…\n"  # 与 backend/app/spill.py MARK 相同
SPILL_KEEP = 50
STDIN_MAX = 64 * 1024  # 走环境变量（base64），单个变量上限 128 KB，留足余量
FLUSH_S = 0.5          # 实时输出多久推一批：太密只是白占带宽

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
    stdin: str | None = None


class Sink:
    """执行线程往里写新输出，推送协程每 FLUSH_S 秒取走一批。"""
    def __init__(self):
        self._buf: list[str] = []
        self._lock = threading.Lock()

    def put(self, text: str) -> None:
        with self._lock:
            self._buf.append(text)

    def take(self) -> str:
        with self._lock:
            out, self._buf = "".join(self._buf), []
        return out


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
        if _outdated(c) and not (c.status == "running" and _busy(pid)):
            c.remove(force=True)  # 装的东西都在工作区里，换镜像不丢
            raise NotFound(name)
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


def _outdated(c) -> bool:
    """容器建于旧镜像（镜像重建过）。查不到当前镜像就当没过期，别因为这个把容器删了。"""
    try:
        return c.image.id != client.images.get(IMAGE).id
    except Exception:  # noqa: BLE001 — docker 查询失败不影响执行
        return False


# 包装脚本：先记下自己的 pid（= 之后 exec 成的 timeout，它自成进程组，停止时整组杀），
# 有 stdin 就从环境变量解码接到标准输入（不在工作区落文件），没有就接 /dev/null，然后才跑真正的命令。
_WRAP = ('echo $$ > /tmp/.exec-{tok}; '
         'if [ -n "${{STDIN_B64+x}}" ]; then exec < <(printf %s "$STDIN_B64" | base64 -d); unset STDIN_B64; '
         'else exec </dev/null; fi; '
         'exec timeout -k 5 {timeout} bash -lc "$1"')


def _exec(pid: str, command: str, timeout: int, stdin: str | None = None, tok: str | None = None,
          sink: Sink | None = None) -> dict:
    c = _container(pid)
    last_used[pid] = time.time()
    tok = tok or os.urandom(6).hex()
    env = {"STDIN_B64": base64.b64encode(stdin.encode()).decode()} if stdin is not None else None
    ex = client.api.exec_create(c.id, ["bash", "-c", _WRAP.format(tok=tok, timeout=timeout), "_", command],
                                workdir="/workspace", environment=env)
    dec, parts = codecs.getincrementaldecoder("utf-8")("replace"), []
    for chunk in client.api.exec_start(ex["Id"], stream=True):
        if text := dec.decode(chunk):
            parts.append(text)
            if sink is not None:
                sink.put(text)
    parts.append(dec.decode(b"", final=True))
    code = client.api.exec_inspect(ex["Id"]).get("ExitCode")
    c.exec_run(["rm", "-f", f"/tmp/.exec-{tok}"], detach=True)
    last_used[pid] = time.time()
    out = "".join(parts)
    result = {"exit_code": code, "timed_out": code == 124, "output": out}
    if len(out) > MAX_OUTPUT:
        head, tail = out[:MAX_OUTPUT // 2], out[-MAX_OUTPUT // 2:]
        result.update(output=head + SPILL_MARK + tail, omitted=len(out) - len(head) - len(tail), total=len(out))
        try:
            result["spill"] = _spill(pid, out)
        except OSError:
            pass
    return result


def _kill_exec(pid: str, tok: str) -> None:
    """后端断开（用户停止了这一轮）：整组 TERM，2 秒后还在就 KILL。"""
    c = _existing(pid)
    if c is None:
        return
    f = f"/tmp/.exec-{tok}"
    c.exec_run(["bash", "-c", f'p=$(cat {f} 2>/dev/null) || exit 0; kill -TERM -- -$p 2>/dev/null; '
                f'sleep 2; kill -KILL -- -$p 2>/dev/null; rm -f {f}; exit 0'])


def _spill(pid: str, text: str) -> str:
    """完整输出存进 /projects/<pid>/.spill/，返回工作区相对路径；只留最近 SPILL_KEEP 个。"""
    d = f"/projects/{pid}/.spill"
    os.makedirs(d, exist_ok=True)
    name = time.strftime("%Y%m%d-%H%M%S", time.gmtime()) + f"-run_command-{os.urandom(2).hex()}.txt"
    with open(f"{d}/{name}", "w", encoding="utf-8") as f:
        f.write(text)
    for path in (d, f"{d}/{name}"):
        os.chown(path, 1000, 1000)
    old = sorted((e for e in os.scandir(d) if e.name.endswith(".txt")), key=lambda e: e.stat().st_mtime, reverse=True)
    for e in old[SPILL_KEEP:]:
        os.unlink(e.path)
    return f".spill/{name}"


def _check_stdin(body: ExecIn) -> None:
    if body.stdin is not None and len(body.stdin.encode()) > STDIN_MAX:
        raise HTTPException(413, f"stdin 超过 {STDIN_MAX // 1024} KB")


@app.post("/exec", dependencies=[Depends(auth)])
async def exec_(body: ExecIn):
    _check_stdin(body)
    return await asyncio.to_thread(_exec, body.project_id, body.command, max(1, min(body.timeout, 120)), body.stdin)


@app.post("/exec/stream", dependencies=[Depends(auth)])
async def exec_stream(body: ExecIn):
    """NDJSON：若干 {"type":"out","data":新输出} → 最后一行 {"type":"exit", 同 /exec 的结果} 或 {"type":"error"}。"""
    _check_stdin(body)
    _container(body.project_id)  # 项目 id 不合法在开流之前就 400
    tok, sink = os.urandom(6).hex(), Sink()
    timeout = max(1, min(body.timeout, 120))

    async def gen():
        task = asyncio.create_task(asyncio.to_thread(_exec, body.project_id, body.command, timeout, body.stdin, tok, sink))
        try:
            while not task.done():
                await asyncio.wait({task}, timeout=FLUSH_S)
                if text := sink.take():
                    yield json.dumps({"type": "out", "data": text}, ensure_ascii=False) + "\n"
            try:
                yield json.dumps({"type": "exit", **task.result()}, ensure_ascii=False) + "\n"
            except Exception as e:  # noqa: BLE001 — docker 出错也要让后端知道这一轮结束了
                yield json.dumps({"type": "error", "error": f"{type(e).__name__}: {e}"}, ensure_ascii=False) + "\n"
        finally:
            if not task.done():  # 客户端断开：命令还在跑就杀掉，不让它在沙盒里空转
                await asyncio.to_thread(_kill_exec, body.project_id, tok)
    return StreamingResponse(gen(), media_type="application/x-ndjson")


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
