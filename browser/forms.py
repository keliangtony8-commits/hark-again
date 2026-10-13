"""云浏览器表单控件（v2.53 CORE 39）：下拉框选哪一项、按键名怎么认——唯一入口，纯函数，service.py 调它。

缺口：网页里的原生下拉框（<select>：省份、日期、人数、证件类型）以前没法选——快照把全部选项文字糊成一个名字，
browser_click 打开的是系统菜单（无头浏览器里看不见也点不到），browser_type 对 <select> 直接报错；
键盘只能随输入框按回车，关弹窗（Esc）、自动补全选第一条（↓ 回车）、Tab 跳格都做不到。

参照：Codex / Gemini CLI / deepseek-harness 都不托管浏览器；语义参照 Playwright MCP 的 browser_select_option /
browser_press_key（按选项文字或值选、按键名用 Playwright 的键名），代码自写。

规则：
- pick(options, want)：options 是页面上该下拉框的全部选项 [{text, value, disabled}]。依次：文字完全相同（空白归一）
  → 值完全相同 → 忽略大小写相同 → 文字里包含 want 且只有一项 → 选中它的下标。禁用的选项不参与；
  一个都对不上 / 包含的不止一项 → PickError，说法里列出可选项（最多 LIST_MAX 个）让模型照抄。
- key(name)：中英文常用说法 → Playwright 键名（ALIASES）；不在 KEYS 里 → KeyError_，列出能按的键。
  不放任意组合键（Ctrl+W 关标签、Ctrl+P 打印这类会把会话弄乱，消费级网页任务也用不上）。
"""
from __future__ import annotations

LIST_MAX = 30   # 对不上时列给模型的选项数

KEYS = ("Enter", "Escape", "Tab", "Shift+Tab", "ArrowDown", "ArrowUp", "ArrowLeft", "ArrowRight",
        "Backspace", "Delete", "Space", "PageDown", "PageUp", "Home", "End")
ALIASES = {
    "enter": "Enter", "return": "Enter", "回车": "Enter", "确认": "Enter",
    "esc": "Escape", "escape": "Escape", "退出": "Escape",
    "tab": "Tab", "shift+tab": "Shift+Tab",
    "down": "ArrowDown", "arrowdown": "ArrowDown", "↓": "ArrowDown", "下": "ArrowDown",
    "up": "ArrowUp", "arrowup": "ArrowUp", "↑": "ArrowUp", "上": "ArrowUp",
    "left": "ArrowLeft", "arrowleft": "ArrowLeft", "←": "ArrowLeft", "左": "ArrowLeft",
    "right": "ArrowRight", "arrowright": "ArrowRight", "→": "ArrowRight", "右": "ArrowRight",
    "backspace": "Backspace", "退格": "Backspace", "delete": "Delete", "del": "Delete",
    "space": "Space", "空格": "Space",
    "pagedown": "PageDown", "pageup": "PageUp", "home": "Home", "end": "End",
}


class PickError(ValueError):
    pass


class KeyError_(ValueError):
    pass


def _norm(s: str) -> str:
    return " ".join(str(s or "").split())


def listing(options: list[dict]) -> str:
    live = [_norm(o.get("text")) for o in options if not o.get("disabled")]
    shown = "、".join(f"「{t}」" for t in live[:LIST_MAX])
    more = f" 等共 {len(live)} 项" if len(live) > LIST_MAX else ""
    return shown + more if live else "（没有可选的项）"


def pick(options: list[dict], want: str) -> int:
    """want 对应的选项下标（在全部 options 里的下标，含禁用项）。对不上 → PickError。"""
    w = _norm(want)
    if not w:
        raise PickError("要选哪一项没写：option 填选项的文字，可选：" + listing(options))
    live = [(i, _norm(o.get("text")), _norm(o.get("value"))) for i, o in enumerate(options) if not o.get("disabled")]
    for test in (lambda t, v: t == w, lambda t, v: v == w, lambda t, v: t.casefold() == w.casefold()):
        hit = [i for i, t, v in live if test(t, v)]
        if hit:
            return hit[0]
    part = [i for i, t, _ in live if w.casefold() in t.casefold()]
    if len(part) == 1:
        return part[0]
    if any(_norm(o.get("text")) == w for o in options if o.get("disabled")):
        raise PickError(f"「{w}」这一项现在是灰的（不可选），可选：" + listing(options))
    if part:
        raise PickError(f"「{w}」对上了不止一项：" + "、".join(f"「{live_text(options, i)}」" for i in part[:LIST_MAX])
                        + "，option 写完整的那一项")
    raise PickError(f"下拉框里没有「{w}」，可选：" + listing(options))


def live_text(options: list[dict], i: int) -> str:
    return _norm(options[i].get("text"))


def key(name: str) -> str:
    """按键说法 → Playwright 键名；不认识 → KeyError_。"""
    raw = str(name or "").strip() or "Enter"
    if raw in KEYS:
        return raw
    k = ALIASES.get(raw.casefold().replace(" ", ""))
    if k is None and raw.casefold() in (x.casefold() for x in KEYS):
        k = next(x for x in KEYS if x.casefold() == raw.casefold())
    if k is None:
        raise KeyError_(f"不能按「{raw}」：只支持 " + "、".join(KEYS) + "。打字用 browser_type。")
    return k
