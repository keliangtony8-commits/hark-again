"""沙盒执行器：唯一接触 Docker 的服务。

- 每个项目一个长驻容器 sbx-<project_id>，工作目录挂载 data/projects/<id>
- 资源限制：内存、CPU、进程数；去掉所有 Linux capability；禁止提权
- 单条命令超时即杀（v2.04：后端带 promote_job 时到点不杀，转成工作区后台任务接着跑，见 _promote）；/exec/stream 边跑边把新输出推给后端（NDJSON，每 FLUSH_S 秒一批，聊天里实时看），
  后端断开（用户点停止）就整组杀掉；可带 stdin（≤ STDIN_MAX，不带则标准输入为空，交互提示不会卡住）；输出太长时给后端开头 + 结尾，完整输出写进工作区 .spill/（约定见 backend/app/spill.py）
- 容器里的家目录在工作区 .home（镜像 /etc/profile.d/workspace.sh）：pip/npm 用户级安装都落在工作区，
  所以容器可以随时删掉重建——镜像更新后（预装清单变了），旧容器在下次用到时自动换成新镜像（有后台任务在跑的不换）
- 空闲超过 IDLE_MINUTES 的容器自动停止，省 VPS 内存（有后台任务在跑的不停）
- 同时开机的容器最多 MAX_RUNNING 台（v1.74，学 E2B 的容量上限，但满了不拒绝）：要开一台新的时，按最久没用先停
  “闲着的”（ROOM_GRACE_S 内没用过、没有前台命令/预览连接、没有后台任务）；都在忙就照开（软上限）。
  另外看宿主机剩余内存（v1.76，/proc/meminfo 的 MemAvailable，容器里读到的就是宿主机的）：开一台新的前，
  剩余内存不够 “一台的上限 SANDBOX_MEM + 留给系统的 SANDBOX_HOST_RESERVE” 时，也按同样顺序先停闲容器，停一台看一次；
  读不到 / 设成 0 就只按台数。4 GB 的 VPS 上后端 + 数据库 + 浏览器已经占一大块，台数上限挡不住各台都吃满的情况
  停机原因（idle 空闲 / room 让位，内存不够也记 room）记在 stopped_by，状态页说清楚；下一条命令把它开起来时结果带 woke，提醒模型之前前台起的程序已停
  （v1.78：stopped_by / woke 落盘到 SANDBOX_STATE，本服务重启 / 更新后不丢；只经 _mark_stopped/_woken/_take_woke/_forget 改）
- 端口预览（/sandboxes/<id>/ports、/preview/<id>/<port>/…）：容器都接在专用网络 SANDBOX_NETWORK 上（本服务也在），
  这里能直连容器里起的网页服务；后端带签名链接把用户的请求转进来（见 backend/app/preview.py），容器端口从不对外暴露
- 出网关卡（v2.37，规则在 egress.py）：每条命令 / 后台任务的环境里带本服务出网代理的账号（HTTP(S)_PROXY），
  公网放行，内网 / 本机 / 云元数据地址拦下；前台命令结果带 egress_blocked，后台任务写 .jobs/<id>/egress。
  compose 里 sandboxes 网络是 internal：容器没有别的出网路。SANDBOX_EGRESS=off 关掉（本机开发）
- 后台任务（/jobs/*）：后端把 .jobs/<id>/run.sh 写进工作区（脚本约定见 backend/app/jobs.py），
  这里只负责 setsid 脱离启动、查活、整组杀掉；日志和退出码都落在工作区文件里，
  所以这个服务或后端重启都不丢任务状态
后端只能通过带 token 的 HTTP 调它，模型永远碰不到 Docker 本身。
"""
import asyncio
import base64
import calendar
import codecs
from collections import deque
import json
import logging
import os
import re
import stat
import threading
import time

import docker
import httpx
from docker.errors import NotFound

import egress as egress_rules
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from starlette.background import BackgroundTask
from pydantic import BaseModel

TOKEN = os.environ["SANDBOX_TOKEN"]
HOST_PROJECTS = os.environ["HOST_PROJECTS_DIR"]  # 宿主机上的绝对路径（Docker 挂载要用）
IMAGE = os.environ.get("SANDBOX_IMAGE", "assistant-sandbox:latest")
MEM = os.environ.get("SANDBOX_MEM", "1g")
CPUS = float(os.environ.get("SANDBOX_CPUS", "1"))
IDLE_MINUTES = int(os.environ.get("SANDBOX_IDLE_MINUTES", "30"))
MAX_RUNNING = int(os.environ.get("SANDBOX_MAX_RUNNING", "3"))  # 同时开机上限；0 = 不限
HOST_RESERVE = os.environ.get("SANDBOX_HOST_RESERVE", "256m")  # 开新容器时宿主机至少还要剩这么多给系统；0 = 不看内存
MEMINFO = "/proc/meminfo"
ROOM_GRACE_S = 60  # 这么久之内用过的不让位：两条命令之间、预览页刚刷新过都算在用
MAX_OUTPUT = 12000
SPILL_MARK = "\n…（中间省略）…\n"  # 与 backend/app/spill.py MARK 相同
PROJECTS_ROOT = "/projects"  # 本服务容器里挂载的全部工作区
SPILL_KEEP = 50
SPILL_DAYS = 30
SPILL_NAME_RE = re.compile(r"^\d{8}-\d{6}-[A-Za-z0-9._~-]{1,160}-[0-9a-f]{4}\.txt$")  # 同 spill.NAME_RE
STDIN_MAX = 64 * 1024  # 走环境变量（base64），单个变量上限 128 KB，留足余量
SINK_MAX = 16000       # 实时推送一批最多带这么多字（后端只显示最近 4000 字）
SPILL_MAX_BYTES = 64 * 1024 * 1024  # 前台命令完整输出落盘上限（与后台任务日志上限 job_log_max_mb 同量级）
BINARY_SAMPLE = 512    # 开头这么多字节里有 NUL 就当二进制输出（同 backend/app/term_text.py）
FLUSH_S = 0.5          # 实时输出多久推一批：太密只是白占带宽
# 沙盒容器接的专用网络（docker-compose.yml 的 sandboxes 网络，本服务也接在上面）：端口预览靠它直连容器。
# 网络不存在（不在 compose 里跑）就退回 Docker 默认网络，只是预览连不上
NETWORK = os.environ.get("SANDBOX_NETWORK", "assistant-sandboxes")
# 停机原因落盘（docker-compose.yml 把 data/sandbox 挂到 /state）：服务重启后状态页和下一条命令仍说得清“为什么停了”
STATE_FILE = os.environ.get("SANDBOX_STATE", "/state/stopped.json")
STATE_KEEP_S = 30 * 86400  # 停了这么久的记录就不留了：再开机时只说“电脑开过机”也无妨
REASONS = ("idle", "room")
PID_RE = re.compile(r"[A-Za-z0-9_-]{1,64}")
# v2.37 出网关卡：代理开在本服务上（sandboxes 网络里容器按服务名 sandbox 找到它）
EGRESS_ON = os.environ.get("SANDBOX_EGRESS", "proxy") != "off"
EGRESS_PORT = int(os.environ.get("SANDBOX_EGRESS_PORT", "3128"))
EGRESS_HOST = os.environ.get("SANDBOX_EGRESS_HOST", "sandbox")  # 容器里看到的本服务地址
log = logging.getLogger("sandbox")

client = docker.from_env()
last_used: dict[str, float] = {}
in_use: dict[str, int] = {}  # 正在跑前台命令 / 开着预览 WebSocket 的容器（计数），让位时跳过
stopped_by: dict[str, tuple[str, float]] = {}  # 我们停掉的容器：(idle | room, 何时)；再开机时挪进 woke
woke: dict[str, str] = {}  # 刚从休眠里开起来、还没告诉过模型的：pid → 当初的停机原因
_state_lock = threading.Lock()  # 写 STATE_FILE（线程池里的请求和 reaper 都会改）
_room_lock = threading.Lock()  # 数开机台数 → 停 → 开 要一气呵成，别两条请求同时挤进来都以为有空位
oom_seen: dict[str, int] = {}  # 每个容器上次看到的 OOM 杀进程次数：前台命令退出 137 时比一比，判断是不是内存打满
app = FastAPI()


def _job_blocked(pid: str, kind: str, tag: str, item: dict) -> None:
    """后台任务（含前台转后台的）被拦：写进工作区 .jobs/<id>/egress，任务结束时后端读给模型。"""
    if kind != "j":
        return
    d = os.path.join(PROJECTS_ROOT, pid, ".jobs", tag)
    if os.path.isdir(d):
        path = os.path.join(d, egress_rules.JOB_FILE)
        egress_rules.append_job_file(path, item)
        _own(path)


egress = egress_rules.Egress(TOKEN, os.environ.get("SANDBOX_ALLOW_HOSTS", ""), os.environ.get("SANDBOX_DENY_HOSTS", ""),
                             on_block=_job_blocked)


def egress_env(pid: str, kind: str, tag: str) -> dict[str, str]:
    """这条命令 / 任务的代理环境变量（写在用户变量之后：同名的以关卡为准）；关卡没开 → 空。"""
    return egress.env(pid, kind, tag, EGRESS_HOST) if EGRESS_ON else {}


def auth(authorization: str = Header("")) -> None:
    if authorization != f"Bearer {TOKEN}":
        raise HTTPException(401)


class ExecIn(BaseModel):
    project_id: str
    command: str
    timeout: int = 60
    stdin: str | None = None
    env: dict[str, str] | None = None  # 用户的命令环境变量（后端 app/command_env.py 给），check_env 把关
    promote_job: str | None = None  # v2.04 只有 /exec/stream 用：到 timeout 还没跑完就转成这个后台任务（不杀）
    promote_max: int = 0            # 转后台后最长跑多久（秒，后端给 job_max_seconds）


# 命令环境变量：名字/个数/长度与后端 app/command_env.py 同一套；系统变量不许覆盖
ENV_NAME_RE = re.compile(r"[A-Z][A-Z0-9_]{1,63}")
ENV_RESERVED = frozenset({"PATH", "HOME", "LANG", "SHELL", "TMPDIR", "USER", "LOGNAME", "TERM", "COLORTERM", "PWD",
                          "OLDPWD", "HOSTNAME", "SHLVL", "IFS", "BASH_ENV", "ENV", "PS1", "LD_PRELOAD",
                          "LD_LIBRARY_PATH", "STDIN_B64"})
ENV_MAX, ENV_VALUE_MAX = 44, 8192  # 用户变量 30 个（command_env.ENV_MAX）+ 借用账户最多 14 个（command_credentials.ENV_EXTRA_MAX）


def check_env(env: dict[str, str] | None) -> dict[str, str]:
    """不合格的整个请求 400（后端已校验过，这里是第二道）。"""
    env = env or {}
    if len(env) > ENV_MAX:
        raise HTTPException(400, "too many env vars")
    for k, v in env.items():
        if not ENV_NAME_RE.fullmatch(k) or k in ENV_RESERVED:
            raise HTTPException(400, f"bad env name {k[:70]}")
        if not isinstance(v, str) or len(v) > ENV_VALUE_MAX or "\x00" in v:
            raise HTTPException(400, f"bad env value for {k}")
    return dict(env)


class Sink:
    """执行线程往里写新输出，推送协程每 FLUSH_S 秒取走一批。一批最多留最后 SINK_MAX 字：
    后端只显示最近几千字，命令狂刷屏时不该在这里攒几百 MB。"""
    def __init__(self):
        self._buf: list[str] = []
        self._size = 0
        self._lock = threading.Lock()

    def put(self, text: str) -> None:
        with self._lock:
            self._buf.append(text)
            self._size += len(text)
            if self._size > SINK_MAX * 2:
                keep = "".join(self._buf)[-SINK_MAX:]
                self._buf, self._size = [keep], len(keep)

    def take(self) -> str:
        with self._lock:
            out, self._buf, self._size = "".join(self._buf), [], 0
        return out[-SINK_MAX:]


# ---- 终端输出（v1.40）----
# ANSI_PATTERN 与 backend/app/term_text.py 一字不差（冒烟测试比对）：Ported from chalk/ansi-regex (MIT)，modified。
ANSI_PATTERN = (
    "(?:\u001B\\][^\u0007\u001B\u009C]*(?:\u0007|\u001B\\x5c|\u009C))|"  # OSC 整段（标题、超链接；ansi-regex 6.2 的写法）
    "[\u001B\u009B][\\[\\]()#;?]*(?:(?:(?:(?:;[-a-zA-Z\\d\\/#&.:=?%@~_]+)*"
    "|[a-zA-Z\\d]+(?:;[-a-zA-Z\\d\\/#&.:=?%@~_]*)*)?(?:\u0007|\u001B\\x5c|\u009C))"
    "|(?:(?:\\d{1,4}(?:;\\d{0,4})*)?[\\dA-PR-TZcf-nq-uy=><~]))"
)
ANSI_RE = re.compile(ANSI_PATTERN)
OSC_HOLD = 1024  # OSC 序列（窗口标题、超链接）可能较长
ESC_HOLD = 64  # 一块输出末尾没收完的转义序列最多留这么长等下一块，再长就不是转义了


class Cleaner:
    """流式去 ANSI：转义序列可能被切在两块之间，末尾半截先扣下，拼到下一块再洗。"""
    def __init__(self):
        self._held = ""

    def feed(self, text: str, final: bool = False) -> str:
        text = self._held + text
        self._held = ""
        if not final:
            i = max(text.rfind("\x1b", len(text) - ESC_HOLD), text.rfind("\x9b", len(text) - ESC_HOLD))
            m = ANSI_RE.match(text, i) if i >= 0 else None
            # 没匹配上，或正好匹配到块尾（"\x1b[3" 本身也算一条完整序列，可能还差 "1m"）：扣下等下一块
            cut = i if i >= 0 and (m is None or m.end() == len(text)) else -1
            o = text.rfind("\x1b]", max(0, len(text) - OSC_HOLD))  # OSC（标题、超链接）还没等到结束符
            if o >= 0 and not re.search("\x07|\x1b\\\\|\x9c", text[o + 2:]):
                cut = o if cut < 0 else min(cut, o)
            if cut >= 0:
                text, self._held = text[:cut], text[cut:]
        return ANSI_RE.sub("", text) if ("\x1b" in text or "\x9b" in text) else text


class HeadTail:
    """Ported from openai/codex codex-rs/core/src/unified_exec/head_tail_buffer.rs (Apache-2.0), modified：按字符计。
    固定上限的缓冲：前一半留最先的输出（head，稳定不变），后一半留最新的（tail），中间丢掉并计数——
    命令刷几个 GB 也只占 MAX 字内存。"""
    def __init__(self, max_chars: int):
        self.head_budget = max_chars // 2
        self.tail_budget = max_chars - self.head_budget
        self.head, self._tail, self._tail_len, self.omitted = [], deque(), 0, 0
        self._head_len = 0

    def push(self, chunk: str) -> None:
        room = self.head_budget - self._head_len
        if room > 0 and chunk:
            self.head.append(chunk[:room])
            self._head_len += len(chunk[:room])
            chunk = chunk[room:]
        if not chunk:
            return
        if self.tail_budget == 0:
            self.omitted += len(chunk)
            return
        if len(chunk) >= self.tail_budget:  # 一块就把尾巴装满：旧尾巴全丢
            self.omitted += self._tail_len + len(chunk) - self.tail_budget
            self._tail, self._tail_len = deque([chunk[-self.tail_budget:]]), self.tail_budget
            return
        self._tail.append(chunk)
        self._tail_len += len(chunk)
        excess = self._tail_len - self.tail_budget
        while excess > 0:
            first = self._tail[0]
            if len(first) <= excess:
                self._tail.popleft()
                self._tail_len -= len(first)
                self.omitted += len(first)
                excess -= len(first)
            else:
                self._tail[0] = first[excess:]
                self._tail_len -= excess
                self.omitted += excess
                excess = 0

    def retained(self) -> int:
        return self._head_len + self._tail_len

    def total(self) -> int:
        return self.retained() + self.omitted

    def parts(self) -> tuple[str, str]:
        return "".join(self.head), "".join(self._tail)

    def text(self) -> str:
        return "".join(self.parts())

    def cut(self) -> tuple[str, str, int]:
        """有省略时给（开头, 结尾, 省略字数）：切口挪到换行处（line_snap），不把一行拦腰截断。"""
        head, tail = self.parts()
        head, tail = line_snap(head, tail)
        return head, tail, self.total() - len(head) - len(tail)


SNAP = 0.2  # 切口往回找换行最多退让这段的 20%（后端 app/spill.py SNAP 同一个数；deploy/host-agent 同一条规则）


def line_snap(head: str, tail: str) -> tuple[str, str]:
    """中间省略处的唯一切口规则：开头截到最后一个完整行（换行本身也省略，标记自带换行），结尾从第一个换行之后开始；
    退让范围内找不到换行（一整行特别长）就照原样切，宁可截半行也不丢一大段。"""
    i = head.rfind("\n", len(head) - int(len(head) * SNAP))
    if i >= 0:
        head = head[:i]
    j = tail.find("\n", 0, int(len(tail) * SNAP))
    if j >= 0:
        tail = tail[j + 1:]
    return head, tail


class JobIn(BaseModel):
    project_id: str
    job_id: str
    env: dict[str, str] | None = None  # 只有 /jobs/start 用：注入给 run.sh 及其子进程


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
    if not PID_RE.fullmatch(pid):
        raise HTTPException(400, "bad project id")
    return pid


def _container(pid: str):
    _check_pid(pid)
    with _room_lock:
        return _open(pid)


def _open(pid: str):
    name = f"sbx-{pid}"
    try:
        c = client.containers.get(name)
        if _outdated(c) and not (c.status == "running" and _busy(pid)):
            c.remove(force=True)  # 装的东西都在工作区里，换镜像不丢
            raise NotFound(name)
        if c.status != "running":
            _make_room(pid)
            c.start()
            _woken(pid)
        return c
    except NotFound:
        _make_room(pid)
        _woken(pid)
        host_dir = os.path.join(HOST_PROJECTS, pid)
        os.makedirs(f"/projects/{pid}", exist_ok=True)
        os.chown(f"/projects/{pid}", 1000, 1000)
        oom_seen[pid] = 0  # 新容器的 cgroup 计数从 0 开始
        extra = {"network": NETWORK} if _network() else {}
        return client.containers.run(
            IMAGE, name=name, detach=True, working_dir="/workspace",
            volumes={host_dir: {"bind": "/workspace", "mode": "rw"}},
            mem_limit=MEM, nano_cpus=int(CPUS * 1e9), pids_limit=256,
            cap_drop=["ALL"], security_opt=["no-new-privileges"],
            labels={"assistant.sandbox": "1"}, **extra,
        )


def room_order(running: dict[str, float], busy_now: set[str], limit: int, now: float) -> tuple[int, list[str]]:
    """要再开一台时：按台数还得停几台、按什么顺序挑（最久没用的在前）。running = 已开机的 {pid: 上次用}（不含要开的那台）；
    busy_now = 正在跑前台命令 / 开着预览的；ROOM_GRACE_S 内用过的也不挑。后台任务要查容器，调用方挑的时候再问。
    limit ≤ 0 时台数不限（need 0），但仍给出顺序，内存不够时用。"""
    order = sorted((t, p) for p, t in running.items() if p not in busy_now and now - t >= ROOM_GRACE_S)
    need = len(running) + 1 - limit if limit > 0 else 0
    return max(need, 0), [p for _, p in order]


def mem_available(text: str) -> int | None:
    """/proc/meminfo 文本 → MemAvailable 字节（内核估的“不换页还能给新程序的内存”）；没有这一行就 None。"""
    m = re.search(r"^MemAvailable:\s+(\d+)\s*kB", text, re.M)
    return int(m.group(1)) * 1024 if m else None


def mem_short(available: int | None, want: int | None, reserve: int | None) -> bool:
    """再开一台会不会把宿主机挤到 reserve 以下：读不到 / 没设上限 / reserve 为 0 都当够。"""
    if available is None or not want or not reserve:
        return False
    return available < want + reserve


def _host_short() -> bool:
    try:
        with open(MEMINFO) as f:
            avail = mem_available(f.read())
    except OSError:
        return False
    return mem_short(avail, mem_bytes(MEM), mem_bytes(HOST_RESERVE))


def _make_room(pid: str) -> None:
    """开机前腾位置（持 _room_lock 调用）：超过 MAX_RUNNING、或宿主机剩余内存不够再开一台，就停最久没用的闲容器；
    挑不出就照开（软上限：命令跑不了比慢一点更糟，真打满了还有容器自己的内存上限兜着）。"""
    short = _host_short()
    if MAX_RUNNING <= 0 and not short:
        return
    try:
        cs = client.containers.list(filters={"label": "assistant.sandbox=1"})
    except Exception:  # noqa: BLE001 — 数不出来就不腾，照常开
        return
    now = time.time()
    running = {c.name[4:]: last_used.get(c.name[4:], 0.0) for c in cs if c.name.startswith("sbx-") and c.name[4:] != pid}
    need, order = room_order(running, {p for p, n in in_use.items() if n > 0}, MAX_RUNNING, now)
    for other in order:
        if need <= 0 and not short:
            break
        if _busy(other):  # 后台任务在跑：算它在用
            continue
        try:
            client.containers.get(f"sbx-{other}").stop(timeout=5)
        except NotFound:
            pass
        except Exception:  # noqa: BLE001 — 停不掉就挑下一台
            continue
        last_used.pop(other, None)
        _mark_stopped(other, "room", now)
        need -= 1
        short = _host_short()  # 停一台看一次：一台空出来的往往就够了


def dump_state(stopped: dict[str, tuple[str, float]], waking: dict[str, str]) -> str:
    """stopped_by + woke → 落盘的 JSON 文本（键排好序，内容不变文件就不变）。"""
    return json.dumps({"stopped": {p: [r, t] for p, (r, t) in stopped.items()}, "woke": waking},
                      ensure_ascii=False, sort_keys=True)


def load_state(text: str, now: float) -> tuple[dict[str, tuple[str, float]], dict[str, str]]:
    """落盘文本 → (stopped_by, woke)。坏 JSON / 坏条目一律丢掉（只认合法项目 id 和 REASONS 里的原因）；
    stopped 里超过 STATE_KEEP_S 的、时间在未来的丢掉；同一台既在 stopped 又在 woke 时以 woke 为准（已经开过机了）。"""
    try:
        raw = json.loads(text)
    except (ValueError, TypeError):
        return {}, {}
    if not isinstance(raw, dict):
        return {}, {}
    stopped: dict[str, tuple[str, float]] = {}
    waking: dict[str, str] = {}
    w = raw.get("woke")
    for p, r in (w.items() if isinstance(w, dict) else ()):
        if isinstance(p, str) and PID_RE.fullmatch(p) and r in REASONS:
            waking[p] = r
    st = raw.get("stopped")
    for p, v in (st.items() if isinstance(st, dict) else ()):
        if not (isinstance(p, str) and PID_RE.fullmatch(p)) or p in waking:
            continue
        if not (isinstance(v, list) and len(v) == 2 and v[0] in REASONS):
            continue
        t = v[1]
        if isinstance(t, bool) or not isinstance(t, (int, float)) or not 0 <= now - t <= STATE_KEEP_S:
            continue
        stopped[p] = (v[0], float(t))
    return stopped, waking


def _save_state() -> None:
    """把 stopped_by / woke 原子写盘（先写临时文件再改名）；写不了只记日志——内存里照常用，只是重启后会忘。"""
    with _state_lock:
        text = dump_state(dict(stopped_by), dict(woke))
        tmp = f"{STATE_FILE}.tmp"
        try:
            os.makedirs(os.path.dirname(STATE_FILE) or ".", exist_ok=True)
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(text)
            os.replace(tmp, STATE_FILE)
        except OSError as e:
            log.warning("save sandbox state failed: %s", e)


def _load_saved() -> None:
    """启动时读回落盘的停机原因（读不到 = 都不知道，跟以前一样）。"""
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return
    stopped, waking = load_state(text, time.time())
    stopped_by.update(stopped)
    woke.update(waking)


def reconcile(stopped: dict[str, tuple[str, float]], waking: dict[str, str],
              states: dict[str, str]) -> tuple[dict[str, tuple[str, float]], dict[str, str]]:
    """读回的记录对一遍现在的容器（states = {pid: running | stopped}）：容器没了（被删 / 重建）的都丢掉；
    记着“我们停的”却在跑（停后被别处开起来、或刚开机还没来得及记就重启了）→ 挪进 woke，下一条命令照样提醒。"""
    s = {p: v for p, v in stopped.items() if p in states}
    w = {p: r for p, r in waking.items() if p in states}
    for p in [p for p in s if states[p] == "running"]:
        w.setdefault(p, s.pop(p)[0])
    return s, w


def _mark_stopped(pid: str, reason: str, t: float) -> None:
    stopped_by[pid] = (reason, t)
    _save_state()


def _woken(pid: str) -> None:
    """容器刚开机：之前是我们停的就记下原因，等下一条命令告诉模型。"""
    reason = stopped_by.pop(pid, None)
    if reason:
        woke[pid] = reason[0]
        _save_state()


def _take_woke(pid: str) -> str | None:
    """取走“刚开机还没告诉模型”的原因（一次性）。"""
    was = woke.pop(pid, None)
    if was:
        _save_state()
    return was


def _forget(pid: str) -> None:
    """容器删了：停机记录一并忘掉。"""
    had = stopped_by.pop(pid, None), woke.pop(pid, None)
    if any(had):
        _save_state()


class _Using:
    """with _Using(pid): 这段时间容器在用，让位时跳过。"""
    def __init__(self, pid: str):
        self.pid = pid

    def __enter__(self):
        in_use[self.pid] = in_use.get(self.pid, 0) + 1

    def __exit__(self, *exc):
        n = in_use.get(self.pid, 1) - 1
        if n > 0:
            in_use[self.pid] = n
        else:
            in_use.pop(self.pid, None)


def _network():
    try:
        return client.networks.get(NETWORK)
    except Exception:  # noqa: BLE001 — 没有专用网络：照常建容器，只是不能预览
        return None


def _address(c) -> str | None:
    """容器在专用网络上的 IP；旧版建的容器不在这个网络上就先接上（不用重建，文件和进程都不动）。"""
    nets = (c.attrs.get("NetworkSettings") or {}).get("Networks") or {}
    if NETWORK not in nets:
        net = _network()
        if net is None:
            return None
        try:
            net.connect(c)
            c.reload()
        except Exception:  # noqa: BLE001
            return None
        nets = (c.attrs.get("NetworkSettings") or {}).get("Networks") or {}
    return (nets.get(NETWORK) or {}).get("IPAddress") or None


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

# v2.06 转后台的命令不再靠本服务转写（CORE 26）：带 promote 时换这个包装脚本。
# 输出经 tee -p 同时进 docker 流（前台实时显示）和工作区 .jobs/.fg-<id>.log；本服务重启、流断了，tee 只是不再写流，文件照写。
# 到点转后台时本服务把这个文件原子改名成 .jobs/<id>/log（tee 开着的文件句柄跟着走），之后的输出不经本服务。
# 命令结束由脚本自己照 run.sh 的约定写结论：.jobs/<id>/ 在（已转后台）→ 内存超上限 touch oom、exit 原子落盘；不在 → 删掉 .fg 文件。
# timeout 放后台跑再 wait：$! 才是进程组组长（pid 文件记它，停止时整组杀）；0<&0 显式接 stdin（否则 & 默认接 /dev/null）。
# .fg 文件建不了（.jobs 没权限 / 盘满）→ F 为空、不 tee：转后台时退回由本服务转写（v2.04 的做法）。
FG_KEEP_MIN = 1440  # 沙盒被停机打断留下的 .fg 文件：一天前的顺手清掉
_WRAP_PROMOTE = ('echo $$ > /tmp/.exec-{tok}; '
                 'if [ -n "${{STDIN_B64+x}}" ]; then exec < <(printf %s "$STDIN_B64" | base64 -d); unset STDIN_B64; '
                 'else exec </dev/null; fi; '
                 'J=.jobs/{jid}; F=.jobs/.fg-{jid}.log; '
                 'mkdir -p .jobs 2>/dev/null; '
                 'find .jobs -maxdepth 1 -name ".fg-*.log" -mmin +' + str(FG_KEEP_MIN) + ' -delete 2>/dev/null; '
                 '{{ : > "$F"; }} 2>/dev/null || F=; '
                 'before=$(' + _OOM + '); '
                 'run() {{ timeout -k 5 {timeout} bash -lc "$1" 0<&0 & echo $! > /tmp/.exec-{tok}; wait $!; '
                 'echo $? > /tmp/.exec-{tok}.rc; }}; '
                 'if [ -n "$F" ]; then run "$1" 2>&1 | tee -p -a "$F"; else run "$1" 2>&1; fi; '
                 'code=$(cat /tmp/.exec-{tok}.rc 2>/dev/null || echo 255); '
                 'if [ -n "$F" ]; then '
                 'if [ -d "$J" ]; then '
                 'after=$(' + _OOM + '); '
                 '[ "$code" = 137 ] && [ -n "$after" ] && [ "$after" -gt "${{before:-0}}" ] && touch "$J/oom"; '
                 '[ -e "$J/exit" ] || {{ echo $code > "$J/exit.tmp" && mv "$J/exit.tmp" "$J/exit"; }}; '
                 'else rm -f "$F"; fi; fi; '
                 'rm -f /tmp/.exec-{tok} /tmp/.exec-{tok}.rc; exit $code')


def _exec(pid: str, command: str, timeout: int, stdin: str | None = None, tok: str | None = None,
          sink: Sink | None = None, env: dict[str, str] | None = None, promote: tuple[str, int] | None = None) -> dict:
    with _Using(pid):
        return _run(pid, command, timeout, stdin, tok, sink, env, promote)


# v2.04 前台超时转后台（Ported from deepseek-ai/deepseek-harness packages/shell/tool-bash promoteOnTimeout (MIT), modified）：
# 带 promote=(job_id, 最长秒数) 时，包装脚本的 timeout 换成后台任务的上限，timeout 秒只是“前台最多等多久”。
# 等到点还没跑完：不杀，现场把它登记成工作区 .jobs/<id>/（cmd.sh、pid=进程组组长、log=到目前为止的全部输出），
# 之后的输出由排水线程接着追加进 log，结束时照 run.sh 的约定原子写 exit（内存超上限再 touch oom）——
# 后端从此按普通后台任务看它（observe / 查活 / 整组杀 / 结束通知）。到点前就结束的照常返回，什么文件都不留。
# v2.06：带 promote 的命令用 _WRAP_PROMOTE，输出由容器里的 tee 直接写文件、结论由包装脚本自己写——转后台之后本服务重启也不丢
# （排水线程只剩把流读空；.fg 文件建不了时才退回由排水线程转写，那种情况下重启仍会判“中断了”）。
PROMOTE_MAX_S = 24 * 3600
PROMOTE_OOM_ADJ = 500  # 同 backend/app/jobs.py OOM_ADJ：转成普通后台任务后内存打满时先杀它，保住常驻服务


def _run(pid: str, command: str, timeout: int, stdin: str | None, tok: str | None, sink: Sink | None,
         env_vars: dict[str, str] | None = None, promote: tuple[str, int] | None = None) -> dict:
    c = _container(pid)
    last_used[pid] = time.time()
    was = _take_woke(pid)
    if pid not in oom_seen:  # 服务刚重启：先记下现有计数，别把以前的 OOM 算到这条命令头上
        oom_seen[pid] = _oom_count(c) or 0
    oom_before = oom_seen.get(pid, 0)
    tok = tok or os.urandom(6).hex()
    env = dict(env_vars or {})  # 用户变量先放，出网代理、STDIN_B64 后写（Codex exec_env：运行时注入的最后写、赢）
    kind, tag = ("j", promote[0]) if promote else ("e", tok)  # 转后台的命令一开始就用任务的账号：转过去之后被拦的也算它的
    env.update(egress_env(pid, kind, tag))
    if stdin is not None:
        env["STDIN_B64"] = base64.b64encode(stdin.encode()).decode()
    env = env or None
    limit = promote[1] if promote else timeout
    wrap = _WRAP_PROMOTE.format(tok=tok, timeout=limit, jid=promote[0]) if promote else _WRAP.format(tok=tok, timeout=limit)
    ex = client.api.exec_create(c.id, ["bash", "-c", wrap, "_", command],
                                workdir="/workspace", environment=env)
    dec, clean, buf = codecs.getincrementaldecoder("utf-8")("replace"), Cleaner(), HeadTail(MAX_OUTPUT)
    spill, sniff, binary_bytes = None, b"", None  # spill：超过 MAX_OUTPUT 才开的落盘文件 _SpillFile
    lock = threading.Lock()
    # 转后台后：teed = 容器里的 tee 在写 .jobs/<id>/log，流里的输出读了就扔；否则 log = 打开的日志，之后的输出只往里写
    moved = {"log": None, "teed": False, "finished": False}

    def take(text: str) -> None:
        nonlocal spill
        if not text:
            return
        with lock:
            if moved["teed"]:
                return
            if moved["log"] is not None:
                try:
                    moved["log"].write(text)
                    moved["log"].flush()  # 后端看 mtime 判卡住、看尾巴给卡片
                except OSError:
                    pass
                return
            if spill is None and buf.total() + len(text) > MAX_OUTPUT:  # 头一次超长：到目前为止的全文还都在 buf 里
                try:
                    spill = _SpillFile(pid)
                    spill.write(buf.text())
                except OSError:
                    spill = False
            if spill:
                spill.write(text)
            buf.push(text)
            if sink is not None:
                sink.put(text)

    def drain() -> None:
        nonlocal sniff, binary_bytes
        for chunk in client.api.exec_start(ex["Id"], stream=True):
            if binary_bytes is not None:
                binary_bytes += len(chunk)
                continue
            if len(sniff) < BINARY_SAMPLE:  # Gemini CLI 的判定：开头采样里有 NUL 就是二进制，之后只计字节数
                sniff += chunk[:BINARY_SAMPLE - len(sniff)]
                if b"\x00" in sniff:
                    binary_bytes = buf.total() + len(chunk)  # 之前的块是 ASCII，字节数 = 字符数
                    continue
            take(clean.feed(dec.decode(chunk)))
        if binary_bytes is None:
            take(clean.feed(dec.decode(b"", final=True), final=True))

    if promote is None:
        try:
            drain()
        finally:
            if spill:
                spill.close()
    else:
        done, errors = threading.Event(), []

        def pump() -> None:
            try:
                drain()
            except Exception as e:  # noqa: BLE001 — docker 流断了：前台照常报错；已转后台就让后端按“中断了”处理
                errors.append(e)
            with lock:
                moved["finished"] = True
                log, teed = moved["log"], moved["teed"]
            done.set()
            if log is not None or teed:
                _promoted_exit(pid, promote[0], ex["Id"], tok, log, oom_before, not errors)

        threading.Thread(target=pump, daemon=True, name=f"exec-{tok}").start()
        if not done.wait(timeout):
            with lock:
                if not moved["finished"]:
                    result = _promote(c, pid, promote[0], command, tok, buf, spill, binary_bytes, timeout)
                    moved["log"] = result.pop("_log")
                    moved["teed"] = moved["log"] is None
                    if was:
                        result["woke"] = was
                    _with_blocked(result, pid, kind, tag)
                    return result
            done.wait()  # 正好在到点那一刻结束：照前台结果给
        if spill:
            spill.close()
        if errors:
            raise errors[0]
    code = client.api.exec_inspect(ex["Id"]).get("ExitCode")
    c.exec_run(["rm", "-f", f"/tmp/.exec-{tok}"], detach=True)
    last_used[pid] = time.time()
    result = {"exit_code": code, "timed_out": code == 124, "output": buf.text()}
    if was:
        result["woke"] = was
    _with_blocked(result, pid, kind, tag)
    if code == 137:  # 被 SIGKILL：看 cgroup 计数有没有涨，涨了就是内存超上限被内核杀的
        n = _oom_count(c)
        if n is not None and n > oom_seen.get(pid, 0):
            result.update(oom=True, memory_limit=mem_bytes(MEM))
        if n is not None:
            oom_seen[pid] = n
    if binary_bytes is not None:
        if spill:
            spill.discard()
        result.update(output="", binary=binary_bytes)
        if sink is not None:
            sink.put(f"（二进制输出，{binary_bytes} 字节，不显示）")
    elif buf.omitted:
        head, tail, omitted = buf.cut()
        result.update(output=head + SPILL_MARK + tail, omitted=omitted, total=buf.total())
        if spill:
            result["spill"] = spill.rel
            if spill.truncated:
                result["spill_truncated"] = True
    return result


def _with_blocked(result: dict, pid: str, kind: str, tag: str) -> None:
    """这条命令跑的时候出网被拦的（[{host, reason}]）带回给后端（app/egress_note.py 说给模型）。"""
    if blocked := egress.take_blocked(egress.user(pid, kind, tag)):
        result["egress_blocked"] = blocked


def _own(path: str) -> None:
    try:
        os.chown(path, 1000, 1000)  # 同 _SpillFile：容器里的用户（后端、命令）都能读写
    except OSError:
        pass


def _promote(c, pid: str, jid: str, command: str, tok: str, buf: HeadTail, spill, binary_bytes, waited: int) -> dict:
    """到点还在跑：登记成 .jobs/<jid>/，返回给后端的结果（带 promoted；_log = 之后由排水线程接着写的日志，None = tee 在写）。
    调用方持着输出锁：这期间排水线程的新输出等着，一个字都不丢、不重复。
    先在 .jobs/.p-<jid>/ 里备齐 cmd.sh / log / pid，再整个改名成 .jobs/<jid>/：包装脚本看到目录就一定是齐的。
    log：优先把 tee 正在写的 .jobs/.fg-<jid>.log 改名进去（全文都在，之后照写）；没有（建不了 / 命令刚好结束删了）
    才退回 v2.04 的做法——把到目前的输出写进去、之后由排水线程转写。"""
    jobs_dir = f"{PROJECTS_ROOT}/{pid}/.jobs"
    d, tmp = f"{jobs_dir}/{jid}", f"{jobs_dir}/.p-{jid}"
    if os.path.exists(d):
        raise FileExistsError(d)
    os.makedirs(tmp, exist_ok=True)
    rel = f".jobs/{jid}/log"
    with open(f"{tmp}/cmd.sh", "w", encoding="utf-8") as f:
        f.write(command + "\n")
    log = None
    try:
        fg = f"{jobs_dir}/.fg-{jid}.log"
        if not stat.S_ISREG(os.lstat(fg).st_mode):  # 只认 tee 建的普通文件（目录 / 符号链接不搬）
            raise IsADirectoryError(fg)
        os.rename(fg, f"{tmp}/log")
        if spill:  # 全文已在 tee 的文件里：spill 那份不要了
            spill.close()
            spill.discard()
    except OSError:
        log = open(f"{tmp}/log", "a", encoding="utf-8")
        if binary_bytes is not None:
            log.write(f"（二进制输出，到目前 {binary_bytes} 字节，不保存）\n")
        elif spill:  # 超长：完整的在 spill 文件里（buf 只有头尾）
            spill.close()
            try:
                with open(spill.path, encoding="utf-8") as f:
                    while part := f.read(1 << 20):
                        log.write(part)
            except OSError:
                log.write(buf.text())
            spill.discard()
        else:
            log.write(buf.text())
        log.flush()
    group = (c.exec_run(["cat", f"/tmp/.exec-{tok}"]).output or b"").decode().strip()
    with open(f"{tmp}/pid", "w") as f:
        f.write(group + "\n")
    if group.isdigit():  # 前台命令没调过 oom_score_adj：转成普通后台任务就和 run.sh 一样调高（只能调高，不需要特权）
        c.exec_run(["bash", "-c", f"for p in $(pgrep -g {group}); do echo {PROMOTE_OOM_ADJ} > /proc/$p/oom_score_adj; "
                    "done 2>/dev/null; exit 0"], detach=True)
    for path in (jobs_dir, tmp, f"{tmp}/cmd.sh", f"{tmp}/log", f"{tmp}/pid"):
        _own(path)
    os.rename(tmp, d)
    out = {"exit_code": None, "timed_out": False, "promoted": jid, "waited": waited, "_log": log}
    if binary_bytes is not None:
        out.update(output="", binary=binary_bytes)
    elif buf.omitted:
        head, tail, omitted = buf.cut()
        out.update(output=head + SPILL_MARK + tail, omitted=omitted, total=buf.total(), spill=rel)
    else:
        out["output"] = buf.text()
    return out


def _promoted_exit(pid: str, jid: str, eid: str, tok: str, log, oom_before: int, clean_end: bool) -> None:
    """转后台的命令结束了：照 run.sh 的约定写结论（exit 原子落盘；内存超上限 touch oom），收拾 pid 文件。
    v2.06 起通常包装脚本已经写过了（有 exit 就不动）；这里兜底 .fg 文件没用上、或命令恰好在登记那一刻结束的情况。
    流是断掉的（不是命令结束）就什么都不写：包装脚本自己会写；它也没写，后端查活发现进程没了、按“中断了”结算。"""
    if log is not None:
        try:
            log.close()
        except OSError:
            pass
    if not clean_end:
        return
    d = f"{PROJECTS_ROOT}/{pid}/.jobs/{jid}"
    if os.path.exists(f"{d}/exit"):
        last_used[pid] = time.time()
        return
    try:
        code = client.api.exec_inspect(eid).get("ExitCode")
        c = _existing(pid)
        if c is not None:
            if code == 137:
                n = _oom_count(c)
                if n is not None and n > oom_before:
                    open(f"{d}/oom", "w").close()
                    _own(f"{d}/oom")
                if n is not None:
                    oom_seen[pid] = n
            c.exec_run(["rm", "-f", f"/tmp/.exec-{tok}"], detach=True)
        with open(f"{d}/exit.tmp", "w") as f:
            f.write(f"{-1 if code is None else code}\n")
        _own(f"{d}/exit.tmp")
        os.replace(f"{d}/exit.tmp", f"{d}/exit")
        last_used[pid] = time.time()
    except Exception:  # noqa: BLE001 — 写不了结论：后端查活兜底
        logging.exception("promoted job %s: writing exit failed", jid)


def _kill_exec(pid: str, tok: str) -> None:
    """后端断开（用户停止了这一轮）：整组 TERM，2 秒后还在就 KILL。"""
    c = _existing(pid)
    if c is None:
        return
    f = f"/tmp/.exec-{tok}"
    c.exec_run(["bash", "-c", f'p=$(cat {f} 2>/dev/null) || exit 0; kill -TERM -- -$p 2>/dev/null; '
                f'sleep 2; kill -KILL -- -$p 2>/dev/null; rm -f {f}; exit 0'])


class _SpillFile:
    """前台命令完整输出边跑边写进 /projects/<pid>/.spill/（v1.40：不再先在内存里攒全文）。约定与 backend/app/spill.py
    相同（v1.38 移植自 deepseek-harness spill-local，MIT）：独占创建不覆盖；超过 SPILL_MAX_BYTES 不再写，标 truncated。"""
    def __init__(self, pid: str):
        self.dir = f"{PROJECTS_ROOT}/{pid}/.spill"
        os.makedirs(self.dir, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
        for _ in range(8):
            name = f"{stamp}-run_command-{os.urandom(2).hex()}.txt"
            try:
                self._f = open(f"{self.dir}/{name}", "x", encoding="utf-8")
                break
            except FileExistsError:
                continue
        else:
            raise FileExistsError(name)
        self.path, self.rel, self.size, self.truncated = f"{self.dir}/{name}", f".spill/{name}", 0, False

    def write(self, text: str) -> None:
        if self.truncated or self._f is None:
            return
        data = text.encode("utf-8")
        room = SPILL_MAX_BYTES - self.size
        if len(data) > room:
            data, self.truncated = data[:room], True
            data = data.decode("utf-8", "ignore").encode("utf-8")  # 别把半个字写进去
        try:
            self._f.write(data.decode("utf-8"))
            self.size += len(data)
        except OSError:  # 磁盘满之类：已写的留着，后面不写了
            self.truncated = True
        if self.truncated:
            try:
                self._f.write("\n…（输出太长，后面没有保存）\n")
            except OSError:
                pass

    def close(self) -> None:
        if self._f is None:
            return
        try:
            self._f.close()
            for path in (self.dir, self.path):
                os.chown(path, 1000, 1000)
        except OSError:
            pass
        self._f = None
        _sweep_spill(self.dir)

    def discard(self) -> None:
        try:
            os.unlink(self.path)
        except OSError:
            pass


def _sweep_spill(d: str) -> None:
    """清理只认 SPILL_NAME_RE 形状的普通文件、不跟随符号链接，严格早于 SPILL_DAYS 天的删、再只留 SPILL_KEEP 个；出错不管。"""
    try:
        cutoff = time.time() - SPILL_DAYS * 86400
        ours = []
        for e in os.scandir(d):
            if SPILL_NAME_RE.match(e.name):
                st = e.stat(follow_symlinks=False)
                if stat.S_ISREG(st.st_mode):
                    ours.append((st.st_mtime, e.path))
        ours.sort(reverse=True)
        for p in dict.fromkeys([p for m, p in ours if m < cutoff] + [p for _, p in ours[SPILL_KEEP:]]):
            try:
                os.unlink(p)
            except FileNotFoundError:
                pass
    except OSError:
        pass


def _check_stdin(body: ExecIn) -> None:
    if body.stdin is not None and len(body.stdin.encode()) > STDIN_MAX:
        raise HTTPException(413, f"stdin 超过 {STDIN_MAX // 1024} KB")


@app.post("/exec", dependencies=[Depends(auth)])
async def exec_(body: ExecIn):
    _check_stdin(body)
    env = check_env(body.env)
    return await asyncio.to_thread(_exec, body.project_id, body.command, max(1, min(body.timeout, 120)), body.stdin,
                                   None, None, env)


@app.post("/exec/stream", dependencies=[Depends(auth)])
async def exec_stream(body: ExecIn):
    """NDJSON：若干 {"type":"out","data":新输出} → 最后一行 {"type":"exit", 同 /exec 的结果} 或 {"type":"error"}。
    带 promote_job：到 timeout 还没结束 → exit 行 exit_code null、promoted=<job id>、output 为到目前的输出（v2.04，见 _run）。"""
    _check_stdin(body)
    env = check_env(body.env)
    _container(body.project_id)  # 项目 id 不合法在开流之前就 400
    tok, sink = os.urandom(6).hex(), Sink()
    timeout = max(1, min(body.timeout, 120))
    promote = None
    if body.promote_job is not None:
        promote = (_check_job(body.promote_job), max(timeout + 1, min(int(body.promote_max or 0), PROMOTE_MAX_S)))

    async def gen():
        task = asyncio.create_task(asyncio.to_thread(_exec, body.project_id, body.command, timeout, body.stdin, tok, sink,
                                                     env, promote))
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
    env = {**check_env(body.env), **egress_env(body.project_id, "j", jid)} or None

    def go():
        c = _container(body.project_id)
        last_used[body.project_id] = time.time()
        _take_woke(body.project_id)  # 任务是新起的，不用提醒“之前的程序停了”
        if c.exec_run(["test", "-f", f".jobs/{jid}/run.sh"], workdir="/workspace").exit_code != 0:
            raise HTTPException(404, "job script missing")
        c.exec_run(["setsid", "-f", "bash", f".jobs/{jid}/run.sh"], workdir="/workspace", detach=True, environment=env)
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
        egress.forget(pid)
        _forget(pid)
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
# v1.94 多一列 pgid（后端把进程归到后台任务名下，算“内存去哪了”），并另给一份按内存排的（memory_top）。
_PS = "ps -eo pid=,pgid=,pcpu=,rss=,etimes=,args= --sort=-pcpu 2>/dev/null"
PROCESS_MAX = 8


def parse_ps(text: str, limit: int | None = PROCESS_MAX) -> list[dict]:
    """ps 输出 → [{pid, pgid, cpu, memory(RSS 字节), elapsed, command}]，保持 ps 的顺序（按 CPU）；limit=None 全要。"""
    out = []
    for line in text.splitlines():
        parts = line.split(None, 5)
        if len(parts) < 6 or not parts[0].isdigit():
            continue
        pid, pg, cpu, rss, et, args = parts
        if args.startswith(("ps -eo", "sleep infinity")) or "/sys/fs/cgroup/memory" in args:
            continue  # 查看命令本身、容器的占位进程
        try:
            out.append({"pid": int(pid), "pgid": int(pg), "cpu": float(cpu), "memory": int(rss) * 1024,
                        "elapsed": int(et), "command": args[:200]})
        except ValueError:
            continue
        if limit is not None and len(out) >= limit:
            break
    return out


def process_tables(text: str) -> dict:
    """{processes: 按 CPU 前 PROCESS_MAX, memory_top: 按内存前 PROCESS_MAX}（同一次 ps）。"""
    rows = parse_ps(text, None)
    return {"processes": rows[:PROCESS_MAX],
            "memory_top": sorted(rows, key=lambda r: (-r["memory"], r["pid"]))[:PROCESS_MAX]}


def _processes(c) -> dict:
    try:
        return process_tables((c.exec_run(["bash", "-c", _PS]).output or b"").decode("utf-8", "replace"))
    except Exception:  # noqa: BLE001
        return {"processes": [], "memory_top": []}


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
               "memory_top": [], "oom_kills": 0, "max_running": MAX_RUNNING}
        try:
            c = client.containers.get(f"sbx-{pid}")
        except NotFound:
            return out
        out.update(state="running" if c.status == "running" else "stopped", outdated=_outdated(c))
        if c.status != "running" and pid in stopped_by:
            out.update(stopped_by=stopped_by[pid][0], stopped_at=stopped_by[pid][1])
        if c.status == "running":
            out.update(**_stats(c), **_processes(c), started_at=_started(c), oom_kills=_oom_count(c) or 0)
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


# 在监听的 TCP 端口 + 是哪个程序：容器里跑一小段 Python（镜像自带），读 /proc/net/tcp{,6} 的 LISTEN 行，
# 再按 socket inode 对回 /proc/<pid>/fd，得到命令行。只监听 127.0.0.1 / ::1 的标 loopback——别的容器（包括这里）连不到它，
# 要让用户预览得改绑 0.0.0.0。
PORTS_PY = r"""
import json, os
ports = {}
LOOP = {"0100007F", "00000000000000000000000001000000", "0000000000000000FFFF00000100007F"}
for f in ("/proc/net/tcp", "/proc/net/tcp6"):
    try:
        rows = open(f).read().splitlines()[1:]
    except OSError:
        continue
    for row in rows:
        p = row.split()
        if len(p) < 10 or p[3] != "0A":
            continue
        addr, port = p[1].rsplit(":", 1)
        e = ports.setdefault(int(port, 16), {"loopback": True, "inodes": set()})
        e["loopback"] = e["loopback"] and addr in LOOP
        e["inodes"].add(p[9])
owner = {}
for pid in filter(str.isdigit, os.listdir("/proc")):
    try:
        fds = os.listdir(f"/proc/{pid}/fd")
    except OSError:
        continue
    for fd in fds:
        try:
            link = os.readlink(f"/proc/{pid}/fd/{fd}")
        except OSError:
            continue
        if link.startswith("socket:["):
            owner.setdefault(link[8:-1], pid)
out = []
for port in sorted(ports):
    e = ports[port]
    pid = next((owner[i] for i in e["inodes"] if i in owner), None)
    cmd = ""
    if pid:
        try:
            cmd = open(f"/proc/{pid}/cmdline", "rb").read().replace(b"\0", b" ").decode("utf-8", "replace").strip()
        except OSError:
            pass
    pgid = None
    if pid:
        try:
            pgid = int(open(f"/proc/{pid}/stat").read().rsplit(")", 1)[1].split()[2])  # 字段 5：进程组（v1.82 端口归哪个常驻服务）
        except (OSError, ValueError, IndexError):
            pass
    out.append({"port": port, "loopback": e["loopback"], "pid": int(pid) if pid else None, "pgid": pgid, "command": cmd[:200]})
print(json.dumps(out))
"""
PORTS_MAX = 20


def parse_ports(text: str) -> list[dict]:
    try:
        rows = json.loads(text.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return []
    return [r for r in rows if isinstance(r, dict) and isinstance(r.get("port"), int)][:PORTS_MAX]


@app.get("/sandboxes/{pid}/ports", dependencies=[Depends(auth)])
async def ports(pid: str):
    """容器里在监听的端口。没在跑 → state 不是 running、列表空（不为看端口开机）。"""
    _check_pid(pid)

    def go() -> dict:
        c = _existing(pid)
        if c is None:
            return {"state": "off", "ports": []}
        out = (c.exec_run(["python3", "-c", PORTS_PY]).output or b"").decode("utf-8", "replace")
        return {"state": "running", "ports": parse_ports(out)}
    return await asyncio.to_thread(go)


# v1.90 每个后台任务占多少 CPU / 内存：任务 = run.sh 记下的进程组（timeout 是组长，见 backend/app/jobs.py script）。
# 容器里跑一小段 Python：读 /proc/<pid>/stat 两次（相隔 GROUP_SAMPLE_S），按进程组累加
#   CPU 节拍 utime+stime+cutime+cstime（含已被父进程收走的子进程，所以中途有子进程退出也不会算多/算少）；
#   内存 = smaps_rollup 的 Pss（共享页按份摊，fork 出来的 worker 不会重复算），读不到退回 RSS。
# 自己 setsid 脱离进程组的（守护进程化）算不进来——那就不归这个任务管了。
GROUP_SAMPLE_S = 0.5
GROUPS_MAX = 20
GROUPS_PY = r"""
import json, os, sys, time
want = {int(a) for a in sys.argv[2:]}
gap = float(sys.argv[1])
tck = os.sysconf("SC_CLK_TCK")
page = os.sysconf("SC_PAGE_SIZE")
def snap():
    out = {}
    for p in filter(str.isdigit, os.listdir("/proc")):
        try:
            f = open(f"/proc/{p}/stat").read().rsplit(")", 1)[1].split()
            g = int(f[2])
            if g in want:
                out[int(p)] = (g, int(f[11]) + int(f[12]) + int(f[13]) + int(f[14]), int(f[21]) * page)
        except (OSError, ValueError, IndexError):
            pass
    return out, time.monotonic()
def pss(p, rss):
    try:
        for line in open(f"/proc/{p}/smaps_rollup"):
            if line.startswith("Pss:"):
                return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        pass
    return rss
a, t0 = snap()
time.sleep(gap)
b, t1 = snap()
groups = {}
for p, (g, ticks, rss) in b.items():
    e = groups.setdefault(g, {"pgid": g, "delta": 0, "ticks": 0, "memory": 0, "processes": 0})
    e["delta"] += max(0, ticks - a[p][1]) if p in a and a[p][0] == g else ticks
    e["ticks"] += ticks
    e["memory"] += pss(p, rss)
    e["processes"] += 1
def box():
    # v1.92 整台沙盒的内存：cgroup v2 memory.current − inactive_file（可回收的文件缓存不算，和 docker stats 一个口径），v1 兜底
    for cur, lim, stat, key in (("memory.current", "memory.max", "memory.stat", "inactive_file"),
                                ("memory/memory.usage_in_bytes", "memory/memory.limit_in_bytes", "memory/memory.stat",
                                 "total_inactive_file")):
        try:
            used = int(open("/sys/fs/cgroup/" + cur).read())
            raw = open("/sys/fs/cgroup/" + lim).read().strip()
            limit = None if raw == "max" else int(raw)
            for line in open("/sys/fs/cgroup/" + stat):
                k, v = line.split()
                if k == key:
                    used -= int(v)
            return {"used": max(0, used), "limit": limit}
        except (OSError, ValueError):
            continue
    return None
print(json.dumps({"tck": tck, "seconds": t1 - t0, "groups": list(groups.values()), "box": box()}))
"""


def group_usage(text: str, cpus: float = CPUS) -> list[dict]:
    """GROUPS_PY 的输出 → [{pgid, cpu（占本沙盒 CPU 配额的百分比 0–100，和电脑卡的 CPU 一个口径）, cpu_seconds, memory, processes}]。
    输出不对 → 空列表（看不到用量不影响任务本身）。"""
    try:
        raw = json.loads(text.strip().splitlines()[-1])
        tck, secs = float(raw["tck"]), float(raw["seconds"])
        rows = raw["groups"]
    except (ValueError, IndexError, KeyError, TypeError):
        return []
    if tck <= 0 or secs <= 0 or not isinstance(rows, list):
        return []
    out = []
    for r in rows:
        try:
            pg, delta, ticks, mem, n = (int(r[k]) for k in ("pgid", "delta", "ticks", "memory", "processes"))
        except (KeyError, TypeError, ValueError):
            continue
        if pg <= 0 or n <= 0 or min(delta, ticks, mem) < 0:
            continue
        cpu = min(100.0, delta / tck / secs * 100 / max(cpus, 0.01))
        out.append({"pgid": pg, "cpu": round(cpu, 1), "cpu_seconds": round(ticks / tck, 1), "memory": mem, "processes": n})
    return out[:GROUPS_MAX]


BOX_LIMIT_MAX = 1 << 50  # cgroup v1 “不限”是个天文数字：当成没上限


def box_usage(text: str) -> dict | None:
    """GROUPS_PY 输出里整台沙盒的内存 → {used, limit}（v1.92，判断“快满了”用）；没有上限或读不到 → None。"""
    try:
        b = json.loads(text.strip().splitlines()[-1])["box"]
        used, limit = b["used"], b["limit"]
    except (ValueError, IndexError, KeyError, TypeError):
        return None
    if type(used) is not int or type(limit) is not int or used < 0 or not 0 < limit < BOX_LIMIT_MAX:
        return None
    return {"used": min(used, limit), "limit": limit}


@app.get("/sandboxes/{pid}/groups", dependencies=[Depends(auth)])
async def groups(pid: str, pgid: list[int] = Query(default=[])):
    """这些进程组现在占多少（后台任务卡、“这台电脑”里的任务行用）。没在跑 → state off、空列表（不为看用量开机）。"""
    _check_pid(pid)
    want = sorted({g for g in pgid if 0 < g < 2 ** 31})[:GROUPS_MAX]

    def go() -> dict:
        c = _existing(pid)
        if c is None:
            return {"state": "off", "groups": []}
        if not want:
            return {"state": "running", "groups": []}
        try:
            cmd = ["python3", "-c", GROUPS_PY, str(GROUP_SAMPLE_S), *map(str, want)]
            out = (c.exec_run(cmd).output or b"").decode("utf-8", "replace")
        except Exception:  # noqa: BLE001
            return {"state": "running", "groups": []}
        return {"state": "running", "groups": group_usage(out), "box": box_usage(out)}
    return await asyncio.to_thread(go)


# 转发时不往下传的头：逐跳头（RFC 9110 §7.6.1）、本服务的鉴权、目标 Host
_HOP = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailer", "trailers",
        "transfer-encoding", "upgrade", "host", "authorization", "content-length"}
_OWN = {"date", "server"}  # uvicorn 自己会加，上游的去掉免得重复
BODY_MAX = 32 * 1024 * 1024
_proxy = httpx.AsyncClient(timeout=httpx.Timeout(60, connect=5), follow_redirects=False)


@app.api_route("/preview/{pid}/{port}/{path:path}", methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
               dependencies=[Depends(auth)])
async def preview(pid: str, port: int, path: str, request: Request):
    """把请求原样转给容器里 port 上的服务，响应边收边回（大文件、长轮询都行）。不开机：休眠了 503 asleep；
    端口上没人 502 no_service。响应头加 X-Sandbox-Preview 方便后端区分“服务自己的 502”和“连不上”。"""
    _check_pid(pid)
    if not 1 <= port <= 65535:
        raise HTTPException(400, "bad port")
    c = await asyncio.to_thread(_existing, pid)
    if c is None:
        raise HTTPException(503, "asleep")
    host = await asyncio.to_thread(_address, c) or c.name
    last_used[pid] = time.time()  # 有人在看预览 = 在用，别空闲回收
    url = httpx.URL(f"http://{host}:{port}/{path}" + (f"?{request.url.query}" if request.url.query else ""))
    headers = [(k, v) for k, v in request.headers.items() if k.lower() not in _HOP]
    body = await request.body()  # 一次读完：分块转发的空请求体会让一些开发服务器（http.server）错位
    if len(body) > BODY_MAX:
        raise HTTPException(413, "too_large")
    req = _proxy.build_request(request.method, url, headers=headers, content=body or None)
    try:
        r = await _proxy.send(req, stream=True)
    except httpx.HTTPError:
        raise HTTPException(502, "no_service")
    out = [(k, v) for k, v in r.headers.multi_items() if k.lower() not in _HOP | _OWN]
    resp = StreamingResponse(r.aiter_raw(), status_code=r.status_code, background=BackgroundTask(r.aclose))
    resp.raw_headers = [(k.encode("latin-1"), v.encode("latin-1")) for k, v in out] + [(b"x-sandbox-preview", b"1")]
    return resp


# ---- WebSocket 转发（Vite/Next 热更新、Streamlit、Gradio、Jupyter 内核）----
# 思路取自 jupyter-server-proxy（BSD-3-Clause）handlers.py 的 proxy_open / select_subprotocol / _record_activity，
# 改进它 issue #459 的毛病：先和上游握手、拿到上游选的子协议，再接受客户端（它是先接受客户端、盲选第一个）。
WS_MAX = 16 * 1024 * 1024  # 单帧上限
# 握手时不往上游传的头：逐跳头 + websockets 自己会生成的握手头 + Origin（预览页是不透明源 Origin: null，
# 不少服务（tornado 系：Streamlit/Jupyter）见到对不上的 Origin 就拒；没有 Origin 头则放行）
_WS_DROP = _HOP | {"sec-websocket-key", "sec-websocket-version", "sec-websocket-extensions", "sec-websocket-protocol",
                   "origin", "cookie2"}


def ws_close_code(code) -> int:
    """上游的关闭码 → 能发给对端的码：1005/1006/1015 是保留码不能发（无码 → 1000，异常断开 → 1011）。"""
    if code in (None, 1005):
        return 1000
    if not isinstance(code, int) or code in (1006, 1015) or not 1000 <= code <= 4999 or 1016 <= code < 3000:
        return 1011
    return code


async def ws_relay(client_ws, upstream, touch=lambda: None) -> None:
    """双向搬运：文本帧仍是文本、二进制仍是二进制；一边断了另一边跟着关，并带上对方的关闭码。"""
    async def down():  # 上游 → 客户端
        try:
            async for msg in upstream:
                touch()
                if isinstance(msg, bytes):
                    await client_ws.send_bytes(msg)
                else:
                    await client_ws.send_text(msg)
        except Exception:
            pass
        code = getattr(upstream, "close_code", None)
        try:
            await client_ws.close(ws_close_code(code))
        except Exception:
            pass

    async def up():  # 客户端 → 上游
        code = 1000
        try:
            while True:
                m = await client_ws.receive()
                if m["type"] == "websocket.disconnect":
                    code = m.get("code", 1000)
                    break
                touch()
                if m.get("bytes") is not None:
                    await upstream.send(m["bytes"])
                elif m.get("text") is not None:
                    await upstream.send(m["text"])
        except Exception:
            pass
        try:
            await upstream.close(ws_close_code(code))
        except Exception:
            pass

    tasks = [asyncio.create_task(down()), asyncio.create_task(up())]
    done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    await asyncio.wait(tasks, timeout=5)
    for t in tasks:
        t.cancel()


@app.websocket("/preview/{pid}/{port}/{path:path}")
async def preview_ws(ws: WebSocket, pid: str, port: int, path: str):
    """和 HTTP 预览同一条路：只连已开着的容器，握手失败（休眠 / 端口上没人 / 鉴权不对）就不接受 → 对端拿到 403。"""
    import websockets
    if ws.headers.get("authorization") != f"Bearer {TOKEN}" or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", pid) or not 1 <= port <= 65535:
        await ws.close(1008)
        return
    c = await asyncio.to_thread(_existing, pid)
    if c is None:
        await ws.close(1013)
        return
    host = await asyncio.to_thread(_address, c) or c.name
    last_used[pid] = time.time()
    query = ws.url.query
    uri = f"ws://{host}:{port}/{path}" + (f"?{query}" if query else "")
    protos = [p.strip() for p in ws.headers.get("sec-websocket-protocol", "").split(",") if p.strip()]
    headers = [(k, v) for k, v in ws.headers.items() if k.lower() not in _WS_DROP]
    try:
        upstream = await websockets.connect(uri, subprotocols=protos or None, additional_headers=headers,
                                            open_timeout=10, max_size=WS_MAX, ping_interval=None, proxy=None)
    except Exception:
        await ws.close(1011)
        return
    await ws.accept(subprotocol=upstream.subprotocol)

    def touch():  # 预览页开着、有来往 = 在用，别空闲回收（jupyter-server-proxy 的 _record_activity）
        last_used[pid] = time.time()
    try:
        with _Using(pid):  # 连着就别让位给别的工作区
            await ws_relay(ws, upstream, touch)
    finally:
        await upstream.close()


async def _reaper():
    while True:
        await asyncio.sleep(60)
        now = time.time()
        for pid, t in list(last_used.items()):
            if now - t > IDLE_MINUTES * 60:
                if await asyncio.to_thread(_busy, pid):  # 后台任务还在跑：算它在用
                    last_used[pid] = now
                    continue
                if in_use.get(pid):  # 前台命令跑得比空闲时限还久 / 预览一直连着
                    last_used[pid] = now
                    continue
                try:
                    await asyncio.to_thread(client.containers.get(f"sbx-{pid}").stop, timeout=5)
                except NotFound:
                    pass
                last_used.pop(pid, None)
                await asyncio.to_thread(_mark_stopped, pid, "idle", now)


def _adopt() -> None:
    """服务重启后 last_used 是空的：把还在跑的沙盒容器认领回来，否则它们永远不会被回收；
    再读回落盘的停机原因，对一遍现有容器。"""
    states: dict[str, str] = {}
    for c in client.containers.list(all=True, filters={"label": "assistant.sandbox=1"}):
        if c.name.startswith("sbx-"):
            states[c.name[4:]] = "running" if c.status == "running" else "stopped"
            if c.status == "running":
                last_used.setdefault(c.name[4:], time.time())
    _load_saved()
    s, w = reconcile(dict(stopped_by), dict(woke), states)
    if (s, w) != (stopped_by, woke):
        stopped_by.clear(); stopped_by.update(s)
        woke.clear(); woke.update(w)
        _save_state()


@app.on_event("startup")
async def _start():
    if EGRESS_ON:
        await egress.start("0.0.0.0", EGRESS_PORT)
    await asyncio.to_thread(_adopt)
    asyncio.create_task(_reaper())
