"""一个会话现在操作哪个标签页（v2.47）——唯一规则，纯逻辑，不碰 Chromium（service.py 照它开 / 关页）。

为什么要有：网站常在新标签页里打开链接（target=_blank、window.open），之前助手还停在旧页上，
点了“没反应”；网页自己 window.close() 或渲染进程崩了（4 GB 小机上大页面被 OOM 杀掉），会话就一直报
“Target closed”，只能等 15 分钟空闲回收。三家参考（Codex / Gemini CLI / deepseek-harness）都不托管浏览器，
没有可搬的代码；语义照 browser-use / Playwright MCP 的做法：新标签自动切过去并告诉模型，页面没了退回上一个。

规则（follow，每个动作前后各看一次）：
1. 当前页崩了 → 关掉它，在同一上下文开新页重新打开它的网址（RELOAD_WINDOW_S 内同一网址已重开过一次
   就不再重开——一打开就崩的页面不无限循环，开空白页说明）。
2. 网站在上次查看之后开了新标签页（还开着、没崩）→ 切到最新那个。
3. 当前页被关了 → 退回还开着的最近一个；一个都没有 → 开空白页。
4. 开着的页超过 TABS_MAX → 关掉最早的（当前页除外），4 GB 机器上每页都是一个渲染进程。
回给模型的说法在后端 app/agent/builtin/browser.py tab_note（kind = opened / closed / crashed / crash_loop / returned）。
"""
from dataclasses import dataclass, field
import time

TABS_MAX = 3
RELOAD_WINDOW_S = 60


@dataclass
class Move:
    page: object | None        # 接下来操作的页；None = service 要新开一页
    kind: str = ""             # "" 没变化 | opened | closed | crashed | crash_loop
    reload: str = ""           # 新开页后要打开的网址（只有 crashed）
    close: list = field(default_factory=list)  # 要关掉的页（崩掉的、超出上限的）


def _url(page) -> str:
    try:
        return page.url or ""
    except Exception:
        return ""


def _live(page, crashed: set[int]) -> bool:
    try:
        return not page.is_closed() and id(page) not in crashed
    except Exception:
        return False


class Tabs:
    def __init__(self, page):
        self.current = page
        self.opened: list = []          # 网站自己开的新页（最新的在后），follow 后清空
        self.crashed: set[int] = set()  # id(page)
        self.reloads: dict[str, float] = {}  # 网址 → 上次因崩溃重开的时间
        self.note: dict | None = None   # 还没告诉模型的变化，进下一张快照
        self.url = _url(page)           # 当前页最后已知的网址（崩了以后 page.url 可能读不到）

    def on_page(self, page) -> None:
        if page is not self.current:
            self.opened.append(page)

    def on_crash(self, page) -> None:
        self.crashed.add(id(page))

    def adopt(self, page) -> None:
        """service 新开的页成为当前页（不算网站开的新标签）。"""
        self.current = page
        self.opened = [p for p in self.opened if p is not page]

    def take_note(self) -> dict | None:
        note, self.note = self.note, None
        return note


def follow(t: Tabs, pages: list, now: float | None = None) -> Move:
    """pages = 上下文里所有页（Chromium 打开顺序）。决定接下来用哪页，并记下要告诉模型的变化。"""
    now = time.time() if now is None else now
    cur = t.current
    if _url(cur) and id(cur) not in t.crashed:
        t.url = _url(cur)
    before = t.url
    close: list = []
    if id(cur) in t.crashed:
        close.append(cur)
        t.opened = [p for p in t.opened if p is not cur]
        last = t.reloads.get(before)
        if before and not before.startswith("about:") and (last is None or now - last > RELOAD_WINDOW_S):
            t.reloads[before] = now
            t.note = {"kind": "crashed", "url": before}
            return Move(None, "crashed", before, close)
        t.note = {"kind": "crash_loop", "url": before}
        return Move(None, "crash_loop", "", close)
    fresh = [p for p in t.opened if p is not cur and _live(p, t.crashed)]
    t.opened = []
    live = [p for p in pages if _live(p, t.crashed)]
    if fresh:
        nxt, kind = fresh[-1], "opened"
    elif not _live(cur, t.crashed):
        nxt, kind = (live[-1] if live else None), "closed"
    else:
        nxt, kind = cur, ""
    keep = [p for p in live if p is not nxt]
    extra = len(keep) + (1 if nxt is not None else 0) - TABS_MAX
    if extra > 0:
        close += keep[:extra]
    if kind:
        n = len(live) - (extra if extra > 0 else 0) + (1 if nxt is None else 0)
        t.note = {"kind": kind, "url": _url(nxt) if nxt is not None else "", "from": before, "tabs": n}
    if nxt is not None:
        t.current = nxt
        t.url = _url(nxt) or t.url
    return Move(nxt, kind, "", close)
