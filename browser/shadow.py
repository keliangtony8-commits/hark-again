"""快照怎么看进网页组件的影子树（open shadow DOM）（v2.62）——唯一规则，纯逻辑，不碰 Chromium。

为什么要有：现在很多消费级网站用 Web Components（Shopify / Salesforce / 银行网银 / 航司选座 / Cookie
同意弹层 / 客服窗 / 谷歌地图的部分控件），按钮和输入框藏在组件的 shadowRoot 里。之前快照用
document.querySelectorAll 和 body.innerText，二者都不进影子树 → 模型看不到“加入购物车”“同意”“登录”，
只能说“页面上没有”。三家参考（Codex / Gemini CLI / deepseek-harness）不托管浏览器 → 自写；语义参照
Playwright MCP 的 aria 快照（影子树内容内联进同一棵树，模型不知道有组件）和 Playwright 的 CSS 定位器
（默认穿透 open shadow root，所以按 ref 点 / 填不用改）。

规则：
1. 只看 open 的影子树；closed 的浏览器不给脚本看，照样看不到（截图 + browser_point 兜底）。
2. 元素：按文档顺序深度优先走，遇到组件先走它的影子树再走它的子元素；和普通元素一样编号，
   不加标签（对模型来说就是页面的一部分；定位器自己穿透）。嵌套超过 DEPTH_MAX 层的不走。
3. 文字：body.innerText 不含影子树里的字。每个看得见的组件影子树出一段（只算它自己这层，
   更深的组件各出各的），标“【组件 · 标签名】”，接在主页面文字后面（内嵌框文字之前，
   它是页面本身的内容）。最多 ROOT_MAX 段，每段最多 TEXT_MAX 字；空的、和已有段落重复的、
   主页面文字里已经有的（插槽里的字）不写。
4. 这些数字由 service 传给快照脚本（JS 里不写死），这里是唯一来源。
"""

DEPTH_MAX = 8
ROOT_MAX = 30
TEXT_MAX = 1000
MIN_TEXT = 2   # 少于这么多字的段落（一个图标、一个 ×）不写


def js_args() -> dict:
    """快照脚本要的参数（规则 2、3 的上限）。"""
    return {"shadowDepth": DEPTH_MAX, "shadowRoots": ROOT_MAX}


def _clean(text: str) -> str:
    lines = [ln.strip() for ln in (text or "").splitlines()]
    out, blank = [], False
    for ln in lines:
        if not ln:
            blank = bool(out)
            continue
        if blank:
            out.append("")
        out.append(ln)
        blank = False
    return "\n".join(out)


def merge_text(main: str, parts: list[tuple[str, str]]) -> str:
    """主页面文字 + 各组件影子树文字（[(标签名, 文字)]）。规则 3。"""
    seen: set[str] = set()
    blocks = []
    for tag, text in parts:
        t = _clean(text)[:TEXT_MAX]
        if len(t) < MIN_TEXT or t in seen or t in main:
            continue
        seen.add(t)
        blocks.append(f"\n\n【组件 · {tag or '组件'}】\n{t}")
        if len(blocks) >= ROOT_MAX:
            break
    return main + "".join(blocks)
