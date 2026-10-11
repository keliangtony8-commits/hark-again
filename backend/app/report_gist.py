"""报告卡的“一眼”：定时任务的结果进 Home 收件箱时，从回复块里取出标题和一句话（纯函数，零模型调用）。

只此一处定规则；worker 投递报告时写进 HomeCard.headline / gist，迁移 0025 用它回填老报告。
客户端只拼这两个字段（headline · gist），横幅、收件箱行、day_overview 都读同一份，不各自猜。

- headline：第一张摘要卡（show_summary）的标题——简报卡自带的大标题，如“今天 · 10月12日 周一”。
- gist：第一段有字的正文（模型在卡后说的那句“今天先做 X”）；没有正文就取摘要卡第一行内容；
  再没有就取全部块的纯文本。Markdown 记号、标题行、列表符号去掉，按句截到 GIST_MAX。
"""
import re

from .blocks import blocks_to_text

HEADLINE_MAX = 80
GIST_MAX = 120

_MARK = re.compile(r"[*_`>~]|!\[[^\]]*\]\([^)]*\)")
_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_BULLET = re.compile(r"^\s*(?:[-+•]|\d+[.、)])\s+")


def _clip(s: str, n: int) -> str:
    s = re.sub(r"\s+", " ", s).strip()
    if len(s) <= n:
        return s
    cut = s[:n]
    # 尽量在句末断开（中英文句号/问叹号/分号），太短就硬截
    m = max(cut.rfind(p) for p in "。！？；!?;")
    return cut[: m + 1] if m >= n // 2 else cut.rstrip() + "…"


def _lines(md: str) -> list[str]:
    """Markdown → 有内容的行：去掉标题行、表格分隔、列表符号和行内记号。"""
    out = []
    for raw in (md or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or re.fullmatch(r"[|:\-\s]+", line):
            continue
        line = _LINK.sub(r"\1", line)
        line = _BULLET.sub("", _MARK.sub("", line)).strip().strip("|").strip()
        if line:
            out.append(re.sub(r"\s*\|\s*", " · ", line))
    return out


def gist(blocks: list[dict]) -> tuple[str | None, str | None]:
    """→ (headline, gist)，取不到就是 None。"""
    blocks = [b for b in blocks or [] if isinstance(b, dict)]
    summary = next((b for b in blocks if b.get("type") == "summary" and str(b.get("title") or "").strip()), None)
    headline = _clip(str(summary["title"]), HEADLINE_MAX) if summary else None

    line = None
    for b in blocks:
        if b.get("type") == "text" and (ls := _lines(str(b.get("text") or ""))):
            line = " ".join(ls)
            break
    if line is None and summary and (ls := _lines(str(summary.get("markdown") or ""))):
        line = ls[0]
    if line is None:
        ls = _lines(blocks_to_text(blocks))
        line = ls[0] if ls else None
    return headline, (_clip(line, GIST_MAX) if line else None)
