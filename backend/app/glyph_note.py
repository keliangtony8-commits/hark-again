"""画出来的字缺字形（会成方块）→ 说给模型的话：唯一入口（v2.40，E2E B13）。

起因：matplotlib 默认 DejaVu Sans 没有中文字形，图里的中文全成豆腐块，模型没看图就交付了。
两层防线：
1. 沙盒镜像带 /etc/matplotlibrc（Noto Sans CJK 优先，sandbox/image/matplotlibrc），workspace-env.sh 在
   用户没有自己的 matplotlibrc 时用 MATPLOTLIBRC 指过去——正常情况根本不缺字；
2. 万一还缺（用户自己改了字体、别的库、字体没装上），matplotlib 会在输出里打
   "Glyph 21608 (\\N{CJK UNIFIED IDEOGRAPH-5468}) missing from font(s) DejaVu Sans."（旧版 "... missing from current font."）。
   这里认出来（字体在、但缓存建在装字体之前也会这样 → 提示删缓存），在命令结果 / 后台任务结束说明后面附一句：图里这些字会是方块，换字体重画，修好前别交付。
refs（Codex / Gemini / deepseek-harness）都没有这类检查 → 自己的规则。
"""
import re
import unicodedata

SHOW = 6            # 最多列几个缺的字
TAIL_BYTES = 65536  # 后台任务只看日志最后这么多

_GLYPH = re.compile(r"Glyph (\d+)(?: \(\\N\{([A-Z0-9 \-]+)\}\))? missing from (?:current font|font\(s\) ([^\n.]+))")


def missing(text: str | None) -> tuple[list[str], list[str]]:
    """输出里 matplotlib 报缺字形的字（去重保序）和当时用的字体名。"""
    chars: dict[str, None] = {}
    fonts: dict[str, None] = {}
    for m in _GLYPH.finditer(text or ""):
        ch = ""
        if m.group(2):
            try:
                ch = unicodedata.lookup(m.group(2))
            except KeyError:
                ch = ""
        if not ch:
            try:
                ch = chr(int(m.group(1)))
            except (ValueError, OverflowError):
                continue
        chars.setdefault(ch, None)
        if m.group(3):
            fonts.setdefault(m.group(3).strip(), None)
    return list(chars), list(fonts)


def _shown(chars: list[str]) -> str:
    vis = [c if c.isprintable() and not c.isspace() else f"U+{ord(c):04X}" for c in chars[:SHOW]]
    return "、".join(vis) + (f" 等 {len(chars)} 个字" if len(chars) > SHOW else "")


def note(text: str | None) -> str:
    """给模型的一段（⚠ 开头、换行结尾）；没缺字 → 空串。"""
    chars, fonts = missing(text)
    if not chars:
        return ""
    used = f"（当时用的字体 {'、'.join(fonts[:2])}）" if fonts else ""
    return (f"⚠ 画图时有字在字体里找不到{used}：{_shown(chars)}——图里这些字会显示成方块。"
            "沙盒装了 Noto Sans CJK：设 plt.rcParams['font.sans-serif'] = ['Noto Sans CJK JP', 'Noto Sans CJK SC', 'DejaVu Sans']、"
            "plt.rcParams['axes.unicode_minus'] = False 后重画（字体名不对就用 fc-list :lang=zh family 查；"
            "字体明明在、设了还报这条，多半是 matplotlib 的字体缓存建在装字体之前：rm -rf \"${XDG_CACHE_HOME:-$HOME/.cache}/matplotlib\" 再画）；"
            "重画到不再出现这条警告之前，别把图发给用户，也别说画好了。\n")


def note_tail(raw: bytes | str | None) -> str:
    """后台任务日志尾部用：只看最后 TAIL_BYTES。"""
    if isinstance(raw, bytes):
        raw = raw[-TAIL_BYTES:].decode("utf-8", errors="replace")
    return note((raw or "")[-TAIL_BYTES:])
