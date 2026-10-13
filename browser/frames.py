"""快照里收哪些内嵌框（iframe）、编号怎么分、文字怎么拼（v2.59）——唯一规则，纯逻辑，不碰 Chromium。

为什么要有：之前快照只看主页面。消费级网站很多关键东西在 iframe 里：支付卡号框（Stripe/支付宝收银台）、
嵌入的登录框、在线表单（问卷、预约）、Cookie 同意弹层、地图/客服窗——模型看不到、也点不到，只能说“页面上没有”。
三家参考（Codex / Gemini CLI / deepseek-harness）都不托管浏览器 → 自写；语义参照 Playwright MCP 的快照
（iframe 内容内联进同一棵树，编号全局唯一，模型不用知道有框）。

规则：
1. 编号全局唯一：主页面先编，内嵌框按文档顺序接着编（模型照样用纯数字 ref，service 记住 ref → 哪个框）。
2. 收哪些框（include）：http(s) / about:blank / about:srcdoc；看得见（有框位置、宽高都 ≥ MIN_SIDE，
   1×1 的统计像素、隐藏的广告框不收）；嵌套不超过 DEPTH_MAX 层；最多 FRAME_MAX 个，多的只报个数。
3. 元素总数仍是 ELEMENT_MAX（主页面优先），框里的元素带 frame 标签（label：别的站 = 它的域名，同站 = “同站”），
   后端 element_line 写成“（内嵌框 js.stripe.com）”。
4. 文字（merge_text）：每个框最多 FRAME_TEXT_MAX 字，接在主页面文字后面，标“【内嵌框 · 标签】”；
   总长不超过 total，主页面至少留 MAIN_MIN 字（框多时先截框，不截主页面）。空框不写。
"""
from urllib.parse import urlparse

FRAME_MAX = 6
DEPTH_MAX = 3
MIN_SIDE = 20
ELEMENT_MAX = 150
FRAME_TEXT_MAX = 1500
MAIN_MIN = 3000


def include(url: str, box: dict | None, depth: int) -> bool:
    """这个框进不进快照。box = 框元素在页面上的位置 {width, height}（None = 看不见 / 已脱离）。"""
    if depth < 1 or depth > DEPTH_MAX or not box:
        return False
    if (box.get("width") or 0) < MIN_SIDE or (box.get("height") or 0) < MIN_SIDE:
        return False
    u = (url or "").strip().lower()
    return u.startswith(("http://", "https://")) or u in ("about:blank", "about:srcdoc")


def label(url: str, page_url: str) -> str:
    """框的标签：和主页面同一个域名（或 about:blank / srcdoc，内容是主页面写进去的）→ “同站”，否则它的域名。"""
    host = (urlparse(url or "").hostname or "").lower()
    main = (urlparse(page_url or "").hostname or "").lower()
    if not host or host == main:
        return "同站"
    return host[4:] if host.startswith("www.") else host


def budget(used: int) -> int:
    """主页面（和前面的框）已经编了 used 个号，下一个框还能编几个。"""
    return max(0, ELEMENT_MAX - used)


def merge_text(main: str, parts: list[tuple[str, str]], total: int) -> str:
    """主页面文字 + 各框文字（[(标签, 文字)]）拼成快照的 text，规则 4。"""
    blocks = []
    for lab, text in parts:
        t = (text or "").strip()
        if t:
            blocks.append(f"\n\n【内嵌框 · {lab}】\n" + t[:FRAME_TEXT_MAX])
    room = total - max(0, min(len(main), MAIN_MIN))
    kept, used = [], 0
    for b in blocks:
        if used + len(b) > room:
            if room - used > 40:
                kept.append(b[: room - used])
                used = room
            break
        kept.append(b)
        used += len(b)
    return main[: max(MAIN_MIN, total - used)] + "".join(kept)
