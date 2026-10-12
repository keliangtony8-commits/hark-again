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
import calendar
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
oom_seen: dict[str, int] = {}  # 每个容器上次看到的 OOM 杀进程次数：前台命令退出 137 时比一比，判断是不是内存打满
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


def _check_pid(pid: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", pid):
        raise HTTPException(400, "bad project id")
    return pid


def _container(pid: str):
    _check_pid(pid)
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
        oom_seen[pid] = 0  # 新容器的 cgroup 计数从 0 开始
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


# OOM 计数：容器自己的 cgroup（v2 memory.events 的 oom_kill；v1 memory.oom_control）。内核在内存超上限时杀进程会加 1。
_OOM = ("sed -n 's/^oom_kill //p' /sys/fs/cgroup/memory.events 2>/dev/null || "
        "sed -n 's/^oom_kill //p' /sys/fs/cgroup/memory/memory.oom_control 2>/dev/null")


def _oom_count(c) -> int | None:
    try:
        out = (c.exec_run(["bash", "-c", _OOM]).output or b"").decode().split()
        return int(out[0]) if out else None
    except Exception:  # noqa: BLE001 — 读不到就不判断
        return None


def mem_bytes(spec: str) -> int | None:
    """SANDBOX_MEM 的 “1g / 512m” → 字节。"""
    m = re.fullmatch(r"(\d+(?:\.\d+)?)([kmg]?)b?", spec.strip().lower())
    if not m:
        return None
    return int(float(m.group(1)) * {"": 1, "k": 1024, "m": 1024 ** 2, "g": 1024 ** 3}[m.group(2)])


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
    if pid not in oom_seen:  # 服务刚重启：先记下现有计数，别把以前的 OOM 算到这条命令头上
        oom_seen[pid] = _oom_count(c) or 0
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
    if code == 137:  # 被 SIGKILL：看 cgroup 计数有没有涨，涨了就是内存超上限被内核杀的
        n = _oom_count(c)
        if n is not None and n > oom_seen.get(pid, 0):
            result.update(oom=True, memory_limit=mem_bytes(MEM))
        if n is not None:
            oom_seen[pid] = n
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
    """删除容器（删项目 / 用户点“重启电脑”）。工作区文件和 .home 里装的东西都在挂载目录里，下次用到时自动重建。"""
    _check_pid(pid)

    def go():
        try:
            client.containers.get(f"sbx-{pid}").remove(force=True)
        except NotFound:
            pass
        last_used.pop(pid, None)
        oom_seen.pop(pid, None)
    await asyncio.to_thread(go)
    return {"ok": True}


def _usage(m: dict) -> int | None:
    """内存已用 = usage 减去可回收的文件缓存（和 docker stats 一样算法），否则读过大文件就像“内存满了”。"""
    usage = m.get("usage")
    if usage is None:
        return None
    st = m.get("stats") or {}
    return max(0, usage - st.get("inactive_file", st.get("total_inactive_file", 0)))


def cpu_percent(stats: dict, cpus: float = CPUS) -> float | None:
    """两次采样之间用掉的 CPU，占这台沙盒 CPU 配额（SANDBOX_CPUS）的百分比，0–100。"""
    cur, pre = stats.get("cpu_stats") or {}, stats.get("precpu_stats") or {}
    try:
        dc = cur["cpu_usage"]["total_usage"] - pre["cpu_usage"]["total_usage"]
        ds = cur["system_cpu_usage"] - pre["system_cpu_usage"]
    except (KeyError, TypeError):
        return None
    if ds <= 0 or dc < 0:
        return None
    online = cur.get("online_cpus") or len(cur["cpu_usage"].get("percpu_usage") or []) or 1
    return round(min(100.0, dc / ds * online * 100 / max(cpus, 0.01)), 1)


def _stats(c) -> dict:
    """{memory_used, memory_limit, cpu_percent}；拿不到的是 None（不影响状态）。"""
    try:
        st = c.stats(stream=False) or {}
    except Exception:  # noqa: BLE001
        return {"memory_used": None, "memory_limit": None, "cpu_percent": None}
    m = st.get("memory_stats") or {}
    return {"memory_used": _usage(m), "memory_limit": m.get("limit"), "cpu_percent": cpu_percent(st)}


# 进程表：按 CPU 排；自己这条查看命令不算。ps 来自镜像里的 procps。
_PS = "ps -eo pid=,pcpu=,rss=,etimes=,args= --sort=-pcpu 2>/dev/null"
PROCESS_MAX = 8


def parse_ps(text: str, limit: int = PROCESS_MAX) -> list[dict]:
    out = []
    for line in text.splitlines():
        parts = line.split(None, 4)
        if len(parts) < 5 or not parts[0].isdigit():
            continue
        pid, cpu, rss, et, args = parts
        if args.startswith(("ps -eo", "sleep infinity")) or "/sys/fs/cgroup/memory" in args:
            continue  # 查看命令本身、容器的占位进程
        try:
            out.append({"pid": int(pid), "cpu": float(cpu), "memory": int(rss) * 1024, "elapsed": int(et),
                        "command": args[:200]})
        except ValueError:
            continue
        if len(out) >= limit:
            break
    return out


def _processes(c) -> list[dict]:
    try:
        return parse_ps((c.exec_run(["bash", "-c", _PS]).output or b"").decode("utf-8", "replace"))
    except Exception:  # noqa: BLE001
        return []


def _started(c) -> float | None:
    raw = ((c.attrs.get("State") or {}).get("StartedAt") or "")[:19]  # 2026-10-12T05:01:02.123456789Z → 秒
    try:
        return float(calendar.timegm(time.strptime(raw, "%Y-%m-%dT%H:%M:%S")))
    except ValueError:
        return None


@app.get("/sandboxes/{pid}/status", dependencies=[Depends(auth)])
async def status(pid: str):
    """只看不启动：容器在不在、在跑没、占多少内存。state：running | stopped（空闲休眠了）| none（还没开过机）。"""
    _check_pid(pid)

    def go() -> dict:
        out = {"state": "none", "memory_used": None, "memory_limit": None, "cpu_percent": None, "started_at": None,
               "outdated": False, "idle_minutes": IDLE_MINUTES, "last_used": last_used.get(pid), "processes": [],
               "oom_kills": 0}
        try:
            c = client.containers.get(f"sbx-{pid}")
        except NotFound:
            return out
        out.update(state="running" if c.status == "running" else "stopped", outdated=_outdated(c))
        if c.status == "running":
            out.update(_stats(c), started_at=_started(c), processes=_processes(c), oom_kills=_oom_count(c) or 0)
        return out
    return await asyncio.to_thread(go)


# 容器自己 /tmp 里的下载缓存（pip / npm，见 workspace-env.sh）：不在工作区里，但占 VPS 的盘，重启也会清掉。
_CLEAN = ('n=$(du -sb /tmp/.cache /tmp/.npm 2>/dev/null | awk \'{s+=$1} END {print s+0}\'); '
          'rm -rf /tmp/.cache /tmp/.npm; echo "$n"')


@app.post("/sandboxes/{pid}/cleanup", dependencies=[Depends(auth)])
async def cleanup(pid: str):
    """清容器里的下载缓存，返回腾出的字节。没在跑就什么都不做（不为清理开机）。"""
    _check_pid(pid)

    def go() -> int:
        c = _existing(pid)
        if c is None or c.status != "running":
            return 0
        try:
            return int((c.exec_run(["bash", "-c", _CLEAN]).output or b"0").decode().split()[-1])
        except (ValueError, IndexError):
            return 0
    return {"freed": await asyncio.to_thread(go)}


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
