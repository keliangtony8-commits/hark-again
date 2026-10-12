#!/usr/bin/env python3
"""主机代理：让助手在 VPS 本机（不是沙盒）以 root 跑命令——服务器主机模式的执行端。只用标准库，Debian 12 自带 python3 就能跑。

安全边界（审批在后端，这里只管“执行得稳”）：
- 只监听 unix socket（默认 /run/assistant-host/agent.sock，root:1000 0660，只挂进 backend/worker 容器），从不开网络端口；
- 每个请求都要 Bearer 令牌（/etc/assistant-host/token，install.sh 生成，同一个写进 .env 的 HOST_AGENT_TOKEN）；
- 每条命令自己一个进程组，超时 / 后端断开（这一轮被停）→ 先 TERM 整组、2 秒后 KILL；
- 输出只回开头 + 结尾（HEAD_TAIL 字符），中间省略，免得一条 journalctl 撑爆后端内存。
协议和沙盒的 /exec/stream 一样：NDJSON {"type":"out","data"} …，最后 {"type":"exit", exit_code, timed_out, output, total, omitted}。

    python3 host_agent.py [--socket PATH] [--token-file PATH]
"""
import argparse
import codecs
import grp
import hmac
import json
import os
import platform
import queue
import select
import signal
import socket
import socketserver
import subprocess
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler

SOCKET = "/run/assistant-host/agent.sock"
TOKEN_FILE = "/etc/assistant-host/token"
SOCKET_GROUP_GID = 1000      # backend 容器里的 app 用户（backend/Dockerfile useradd -u 1000）
TIMEOUT_MAX = 600            # 与后端 settings.host_command_max_seconds 同
BODY_MAX = 64 * 1024
HEAD_TAIL = 16000            # 回给后端的输出字符上限（开头一半 + 结尾一半）
FLUSH_S = 0.5                # 实时输出的推送间隔（同沙盒 FLUSH_S）
OUT_EVENT_MAX = 8000         # 每个 out 事件最多带多少字符（实时画面只看最后几十行）
KILL_GRACE = 2.0
CWD = "/root"
ENV = {"PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin", "HOME": "/root", "LANG": "C.UTF-8",
       "LC_ALL": "C.UTF-8", "DEBIAN_FRONTEND": "noninteractive", "SYSTEMD_PAGER": "", "PAGER": "cat",
       "GIT_PAGER": "cat", "TERM": "dumb", "NEEDRESTART_MODE": "a"}


class HeadTail:
    """按字符预算留开头和结尾（Codex unified_exec head_tail_buffer 的同款思路；后端 sandbox/runner.py 也有一份）。"""

    def __init__(self, budget: int = HEAD_TAIL):
        self.head_max, self.tail_max = budget // 2, budget - budget // 2
        self.head, self.tail, self.tail_len, self.total = [], deque(), 0, 0
        self.head_len = 0

    def push(self, text: str) -> None:
        self.total += len(text)
        if self.head_len < self.head_max:
            take = text[: self.head_max - self.head_len]
            self.head.append(take)
            self.head_len += len(take)
            text = text[len(take):]
        if not text:
            return
        self.tail.append(text)
        self.tail_len += len(text)
        while self.tail_len - len(self.tail[0]) >= self.tail_max:
            self.tail_len -= len(self.tail.popleft())

    def result(self) -> tuple[str, int]:
        head = "".join(self.head)
        tail = "".join(self.tail)
        if len(tail) > self.tail_max:
            tail = tail[-self.tail_max:]
        omitted = self.total - len(head) - len(tail)
        if omitted <= 0:
            return head + tail, 0
        return f"{head}\n…（中间省略 {omitted} 字符）…\n{tail}", omitted


def host_info() -> dict:
    pretty = ""
    try:
        with open("/etc/os-release") as f:
            for line in f:
                if line.startswith("PRETTY_NAME="):
                    pretty = line.split("=", 1)[1].strip().strip('"')
    except OSError:
        pass
    try:
        with open("/proc/uptime") as f:
            uptime = int(float(f.read().split()[0]))
    except (OSError, ValueError, IndexError):
        uptime = None
    return {"hostname": socket.gethostname(), "os": pretty or platform.platform(), "kernel": platform.release(),
            "arch": platform.machine(), "uptime_seconds": uptime, "user": "root" if os.geteuid() == 0 else str(os.geteuid()),
            "timeout_max": TIMEOUT_MAX}


def kill_group(proc: subprocess.Popen) -> None:
    for sig, wait in ((signal.SIGTERM, KILL_GRACE), (signal.SIGKILL, 1.0)):
        if proc.poll() is not None:
            return
        try:
            os.killpg(proc.pid, sig)
        except ProcessLookupError:
            return
        try:
            proc.wait(wait)
        except subprocess.TimeoutExpired:
            pass


def run(command: str, timeout: int, send, gone=lambda: False) -> None:
    """跑一条命令，把事件交给 send(dict)；send 抛 OSError 或 gone() 为真 = 后端断开 → 杀整组、不再发。
    gone 每个推送间隔看一次：命令一声不吭（sleep、卡住）时也能发现这一轮被停了。"""
    proc = subprocess.Popen(["bash", "-lc", command], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            stdin=subprocess.DEVNULL, cwd=CWD if os.access(CWD, os.X_OK) else "/", env=ENV,
                            start_new_session=True)
    chunks: "queue.Queue[bytes | None]" = queue.Queue()

    def pump() -> None:
        for data in iter(lambda: proc.stdout.read1(65536), b""):
            chunks.put(data)
        chunks.put(None)

    threading.Thread(target=pump, daemon=True).start()
    decoder = codecs.getincrementaldecoder("utf-8")("replace")
    keep, pending, done = HeadTail(), [], False
    deadline = time.monotonic() + timeout
    last_flush = time.monotonic()
    timed_out = False
    try:
        while not done:
            left = deadline - time.monotonic()
            if left <= 0:
                if timed_out:  # 杀过还有人占着输出管道（脱离进程组的孙进程）：不再等它
                    break
                timed_out = True
                kill_group(proc)
                left = KILL_GRACE  # 让剩下的输出读完
                deadline = time.monotonic() + KILL_GRACE + 1
            try:
                data = chunks.get(timeout=min(FLUSH_S, max(left, 0.05)))
            except queue.Empty:
                data = b""
            if gone():
                raise BrokenPipeError("client gone")
            if data is None:
                done = True
                text = decoder.decode(b"", final=True)
            else:
                text = decoder.decode(data)
            if text:
                keep.push(text)
                pending.append(text)
            now = time.monotonic()
            if pending and (done or now - last_flush >= FLUSH_S):
                out = "".join(pending)[-OUT_EVENT_MAX:]
                pending.clear()
                last_flush = now
                send({"type": "out", "data": out})
        code = proc.wait()
        output, omitted = keep.result()
        send({"type": "exit", "exit_code": code, "timed_out": timed_out, "output": output,
              "total": keep.total, "omitted": omitted})
    except OSError:  # 后端断了：这一轮被停了，命令也停
        kill_group(proc)
    finally:
        if proc.poll() is None:
            kill_group(proc)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "assistant-host"
    token = ""

    def address_string(self) -> str:  # unix socket 没有对端地址
        return "unix"

    def log_message(self, fmt, *args) -> None:  # 不把命令写进系统日志（可能带参数里的敏感值）
        pass

    def _authorized(self) -> bool:
        got = self.headers.get("Authorization", "")
        return bool(self.token) and hmac.compare_digest(got.encode(), f"Bearer {self.token}".encode())

    def _json(self, code: int, body: dict) -> None:
        data = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        if not self._authorized():
            return self._json(401, {"error": "unauthorized"})
        if self.path == "/health":
            return self._json(200, host_info())
        self._json(404, {"error": "not found"})

    def do_POST(self) -> None:
        if not self._authorized():
            return self._json(401, {"error": "unauthorized"})
        if self.path != "/exec/stream":
            return self._json(404, {"error": "not found"})
        size = int(self.headers.get("Content-Length") or 0)
        if size <= 0 or size > BODY_MAX:
            return self._json(413 if size > BODY_MAX else 400, {"error": "bad body"})
        try:
            body = json.loads(self.rfile.read(size))
            command = body["command"]
            timeout = int(body.get("timeout") or 60)
        except (ValueError, KeyError, TypeError):
            return self._json(400, {"error": "bad json"})
        if not isinstance(command, str) or not command.strip():
            return self._json(400, {"error": "empty command"})
        timeout = max(1, min(timeout, TIMEOUT_MAX))
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()

        def send(ev: dict) -> None:
            line = (json.dumps(ev, ensure_ascii=False) + "\n").encode()
            self.wfile.write(f"{len(line):x}\r\n".encode() + line + b"\r\n")
            self.wfile.flush()

        def gone() -> bool:
            try:
                readable, _, _ = select.select([self.connection], [], [], 0)
                return bool(readable) and self.connection.recv(1, socket.MSG_PEEK) == b""
            except OSError:
                return True

        try:
            run(command, timeout, send, gone)
            self.wfile.write(b"0\r\n\r\n")
            self.wfile.flush()
        except OSError:
            pass
        self.close_connection = True


class Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True
    allow_reuse_address = True


def serve(path: str, token: str, gid: int | None = SOCKET_GROUP_GID) -> Server:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.exists(path):
        os.unlink(path)
    Handler.token = token
    old = os.umask(0o117)
    try:
        srv = Server(path, Handler)
    finally:
        os.umask(old)
    os.chmod(path, 0o660)
    if gid is not None and os.geteuid() == 0:
        os.chown(path, 0, gid)
    return srv


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--socket", default=os.environ.get("HOST_AGENT_SOCKET", SOCKET))
    ap.add_argument("--token-file", default=os.environ.get("HOST_AGENT_TOKEN_FILE", TOKEN_FILE))
    a = ap.parse_args()
    with open(a.token_file) as f:
        token = f.read().strip()
    if len(token) < 16:
        raise SystemExit("令牌太短（至少 16 个字符）")
    try:
        gid = grp.getgrgid(SOCKET_GROUP_GID).gr_gid
    except KeyError:
        gid = SOCKET_GROUP_GID
    serve(a.socket, token, gid).serve_forever()


if __name__ == "__main__":
    main()
