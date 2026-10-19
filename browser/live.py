# Copyright (c) 2026 The BetterWright Project and contributors (MIT License)
# Ported from betterwright/src/live-view.ts (MIT), modified: Python, our 0–1 input protocol, no HTTP viewer/login/tabs strip.
"""实时画面（v2.89 §M）的唯一规则：纯逻辑，不碰 Playwright。service.py 只接线（WS /sessions/{name}/live + CDP screencast）。

- 推帧：latest-frame-wins——每个观看者只留一帧没发的（新帧覆盖旧帧），网慢的人自动跳帧，绝不排队拖住别人；
  新连上的人立刻拿到最后一帧（不黑屏）。
- 分辨率：观看者报自己画面的物理像素宽，取最大值按 VIEWPORT_BUCKET_PX 分桶（拖窗口不会每像素重启一次 screencast），
  夹在 [MIN_DIMENSION, cap]；没人报 → cap。
- 输入：客户端发 JSON（坐标 0–1，和 v2.82 接管页同一套语义），这里夹取、白名单、截断后才交给 service。
- 点一下（v3.5.x 接管点不动 Turnstile 查根因）：注入的是一只真鼠标会产生的完整序列——从上一次的位置移过去（中途
  APPROACH_STEPS 个 mouseMoved，网页 / iframe 收到 pointerover → pointermove…）→ 按下 → 按住用户真实按了多久
  （客户端量的 hold，毫秒）→ 抬起。以前是 page.mouse.click：指针瞬移到点上、按下抬起同一毫秒，
  跨源 iframe（Turnstile）收到的是“没移动过、0ms 按压”的点击。hold 不是编的：App / 网页按真实按下→抬起的时间报。
- 悬停：没按住时的 move = 鼠标移过（网页版电脑端、App 外接鼠标转发真实移动），下拉菜单、悬停才出现的按钮才点得到。
"""
import asyncio
import json
import math

DEFAULT_QUALITY = 60          # JPEG 质量（BetterWright DEFAULT_QUALITY）
MAX_DIMENSION = 1280          # 最长边上限（= 视口宽；手机自动更小）
MIN_DIMENSION = 320
VIEWPORT_BUCKET_PX = 160      # 观看窗口宽按 160px 一档
SCROLL_MAX = 3000             # 一次滚轮最多滚多少像素（原 service.SCROLL_MAX）
TEXT_MAX = 8192               # 一次打字最多多少字（BetterWright insertText 上限）
CLICK_HOLD_MS = 80            # 老客户端不报 hold 时按这么久（普通人点鼠标 / 轻触的典型按压时长量级）
HOLD_MAX_MS = 1000            # 再长就是长按：客户端走 down → move → up，不走 click
APPROACH_STEPS = 6            # 点之前从上一个位置移过去，中途发几个 mouseMoved
MOUSE_KINDS = ("click", "down", "move", "up")
NAV_ACTIONS = ("back", "reload")
# 能原样按下的键（网页版直接打字时转发的那些；其余可见字符当文字）
KEYS = frozenset({"Enter", "Backspace", "Tab", "Delete", "Escape", "ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight",
                  "Home", "End", "PageUp", "PageDown"})

# WS 关闭码（客户端据此进不同状态；= App models/browser_view.dart / 网页 lib/browserView.ts）
CLOSE_UNAUTHORIZED = 4401
CLOSE_BAD_NAME = 4400
CLOSE_NOT_OPEN = 4404      # 浏览器已关闭（没开过 / 空闲回收 / 容器重启）→ 客户端显示“重新打开”
CLOSE_DOWN = 4503          # 浏览器服务本身起不来


def _num(v, default: float = 0.0) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return default
    return f if math.isfinite(f) else default


def _clamp(v: float, lo: float, hi: float) -> float:
    return min(max(v, lo), hi)


def effective_max_width(viewer_px, cap: int = MAX_DIMENSION) -> int:
    """所有观看者里最宽的那个，按桶向上取整，夹在 [MIN_DIMENSION, cap]；没人报宽度 → cap。"""
    want = max((p for p in viewer_px if p and p > 0), default=0)
    if want < 1:
        return cap
    return int(_clamp(math.ceil(want / VIEWPORT_BUCKET_PX) * VIEWPORT_BUCKET_PX, MIN_DIMENSION, cap))


def parse(raw: str) -> dict | None:
    """一条客户端消息 → 干净的命令；看不懂 / 越界的 → None（丢掉，不报错，不断线）。
    {"t":"mouse","kind":"click|down|move|up","x":0–1,"y":0–1[,"hold":按了多少毫秒（click）]}
    {"t":"wheel","x","y","dx","dy"}     {"t":"text","text"}     {"t":"key","key"}
    {"t":"nav","action":"back|reload"}  {"t":"view","px":画面物理像素宽}"""
    try:
        m = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if not isinstance(m, dict):
        return None
    t = m.get("t")
    unit = lambda k, d=0.5: _clamp(_num(m.get(k), d), 0.0, 1.0)  # noqa: E731
    if t == "mouse":
        kind = m.get("kind", "click")
        if kind not in MOUSE_KINDS:
            return None
        out = {"t": "mouse", "kind": kind, "x": unit("x"), "y": unit("y")}
        if kind == "click":
            out["hold"] = int(_clamp(_num(m.get("hold"), CLICK_HOLD_MS), 0, HOLD_MAX_MS))
        return out
    if t == "wheel":
        return {"t": "wheel", "x": unit("x"), "y": unit("y"),
                "dx": _clamp(_num(m.get("dx")), -SCROLL_MAX, SCROLL_MAX), "dy": _clamp(_num(m.get("dy")), -SCROLL_MAX, SCROLL_MAX)}
    if t == "text":
        text = str(m.get("text") or "")[:TEXT_MAX]
        return {"t": "text", "text": text} if text else None
    if t == "key":
        key = m.get("key")
        return {"t": "key", "key": key} if key in KEYS else None
    if t == "nav":
        return {"t": "nav", "action": m["action"]} if m.get("action") in NAV_ACTIONS else None
    if t == "view":
        return {"t": "view", "px": int(_clamp(_num(m.get("px")), 0, 10_000))}
    return None


class Viewer:
    """一个观看者（一条 WS）：只存一帧没发的（latest-frame-wins）。"""

    def __init__(self) -> None:
        self.px = 0
        self._frame: bytes | None = None
        self._sent: bytes | None = None
        self._ready = asyncio.Event()
        self.closed = False

    def offer(self, frame: bytes) -> None:
        if frame is self._sent or self.closed:
            return  # 同一帧不发两次（广播和“新连接补帧”撞在一起时）
        self._frame = frame
        self._ready.set()

    async def next(self) -> bytes | None:
        """等下一帧；关了 → None。"""
        while not self.closed:
            await self._ready.wait()
            self._ready.clear()
            frame, self._frame = self._frame, None
            if frame is not None:
                self._sent = frame
                return frame
        return None

    def close(self) -> None:
        self.closed = True
        self._ready.set()


class Hub:
    """一个会话的所有观看者 + 最后一帧。"""

    def __init__(self) -> None:
        self.viewers: set[Viewer] = set()
        self.last: bytes | None = None

    def join(self, v: Viewer) -> None:
        self.viewers.add(v)
        if self.last is not None:
            v.offer(self.last)  # 新连接立刻补最后一帧

    def leave(self, v: Viewer) -> None:
        v.close()
        self.viewers.discard(v)

    def deliver(self, frame: bytes) -> None:
        self.last = frame
        for v in self.viewers:
            v.offer(frame)

    def width(self, cap: int = MAX_DIMENSION) -> int:
        return effective_max_width([v.px for v in self.viewers], cap)

    def close_all(self) -> list[Viewer]:
        out = list(self.viewers)
        for v in out:
            v.close()
        self.viewers.clear()
        return out
