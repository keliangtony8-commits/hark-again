"""回复里“日期 + 星期几”对不上日历时就地改正（唯一入口，v2.70 E2E B37）。

真机 E2E r8：回复写“11月3日（周一）”，2026-11-03 其实是周二——绝对日期的星期几是模型心算的，
常常差一天（拿去年的日历、或从今天往后数错）。相对日期有 clock.resolve 工具兜底，绝对日期没有。
三家参考（Codex / Gemini CLI / deepseek-harness）都只在上下文里放“今天是…”，不检查回复里的日期，
所以自写本地规则：星期几是日期的函数，错了不必再问模型，零额外调用、确定改对。

- fix(reply, question, today) → (改好的回复, [(原写法, 新写法)])；没错 → (原文, [])。
  认的写法：2026年11月3日（周一）/ 11月3日 周一 / 11月3号星期一 / 2026-11-03（周一）/ 11/3（周一）/
  周一（11月3日）/ Monday, November 3 / Nov 3 (Mon)。星期紧挨日期（中间至多一个括号、逗号、空格或表格竖线）才算一对。
- 年份：日期自带年份用它；没带时，回复和用户原话里只出现一个年份就用那个，否则取离今天最近的那一年
  （10 月说“1月5日”= 明年 1 月）。
- 不改的情况（宁可漏，不可错改）：
  · 星期后面紧跟“至 / 到 / - / ~”或“、三”——那是一段日期的星期范围或几天（“11月3日（周一至周三）”）；
  · 这对写法在用户原话里原样出现（在复述用户的话）；
  · 在引号里，或附近有“实际 / 其实 / 应为 / 写错 / 有误 / 不对 / actually / should be”（在指出别人写错）；
  · 日期本身不存在（2月30日）。
- 改写保留原来的写法：周 / 星期 / 礼拜 照旧，英文全称 / 缩写照旧。
"""
from __future__ import annotations

import calendar
import re
from datetime import date, datetime

from ..clock import WEEKDAYS, zone

YEAR_SPAN = 1  # 没写年份时只在今年前后一年里取最近的
NEAR = 30      # “实际 / 写错…”离这对写法多远（字）内算在纠错

_CN_WD = r"(?P<wp>周|星期|礼拜)(?P<wd>[一二三四五六日天])"
_CN_DATE = (r"(?:(?P<y>\d{4})\s*年\s*)?(?P<m>\d{1,2})\s*月\s*(?P<d>\d{1,2})\s*[日号]"
            r"|(?P<y2>\d{4})[-/.](?P<m2>\d{1,2})[-/.](?P<d2>\d{1,2})(?![\d])"
            r"|(?<![\d/.])(?P<m3>\d{1,2})/(?P<d3>\d{1,2})(?![\d/])")
_GAP = r"\s*[（(，,|｜]?\s*"  # 表格里相邻两列“| 11月5日 | 星期四 |”也算一对
_RANGE_AFTER = re.compile(r"\s*(?:[至到\-–—~～]|[、和及]\s*(?:周|星期|礼拜)?[一二三四五六日天])")
CN_AFTER = re.compile(rf"(?P<date>{_CN_DATE}){_GAP}{_CN_WD}")
CN_BEFORE = re.compile(rf"{_CN_WD}\s*[（(]\s*(?P<date>{_CN_DATE})\s*[）)]")

_MONTHS = {m.lower(): i for i, m in enumerate(calendar.month_name) if m}
_MONTHS.update({m.lower(): i for i, m in enumerate(calendar.month_abbr) if m})
_MONTHS["sept"] = 9
_EN_DAYS = list(calendar.day_name)
_EN_WD = r"(?P<ewd>Mon(?:day)?|Tue(?:s|sday)?|Wed(?:nesday)?|Thu(?:r|rs|rsday)?|Fri(?:day)?|Sat(?:urday)?|Sun(?:day)?)\.?"
_EN_MONTH = r"(?P<emon>" + "|".join(sorted((re.escape(k) for k in _MONTHS), key=len, reverse=True)) + r")\.?"
_EN_DATE = rf"{_EN_MONTH}\s+(?P<ed>\d{{1,2}})(?:st|nd|rd|th)?(?:,?\s+(?P<ey>\d{{4}}))?"
EN_BEFORE = re.compile(rf"\b{_EN_WD},?\s+{_EN_DATE}\b", re.I)
EN_AFTER = re.compile(rf"\b{_EN_DATE}\s*[(,]\s*{_EN_WD}\b", re.I)

_QUOTES = "「」『』“”\"'‘’《》"
_DISPUTE = re.compile(r"实际|其实|应为|应该是|写错|有误|不对|笔误|错了|actually|should be|incorrect|wrong", re.I)
_YEAR = re.compile(r"(?<!\d)(?:19|20)\d{2}(?=\s*年|[-/.]\d{1,2}[-/.]|\b)")


def _year_hint(*texts: str) -> int | None:
    years = {int(y) for t in texts for y in _YEAR.findall(t or "")}
    return years.pop() if len(years) == 1 else None


def _pick_year(m: int, d: int, today: date, hint: int | None) -> int | None:
    if hint:
        return hint
    best = None
    for y in range(today.year - YEAR_SPAN, today.year + YEAR_SPAN + 1):
        try:
            dist = abs((date(y, m, d) - today).days)
        except ValueError:
            continue
        if best is None or dist < best[0]:
            best = (dist, y)
    return best[1] if best else None


def _real(y: int | None, m: int, d: int) -> date | None:
    try:
        return date(y, m, d) if y else None
    except ValueError:
        return None


def _quoted(text: str, a: int, b: int) -> bool:
    """这对写法在一对引号里（左边最近的引号是开引号且右边有收引号）。"""
    left = max((text.rfind(q, 0, a) for q in "「『“《‘\""), default=-1)
    if left < 0:
        return False
    close = {"「": "」", "『": "』", "“": "”", "《": "》", "‘": "’", "\"": "\""}[text[left]]
    end = text.find(close, b)
    return end >= 0 and (text.rfind(close, left + 1, a) < 0)


def _disputed(text: str, a: int, b: int) -> bool:
    return bool(_DISPUTE.search(text[max(0, a - NEAR): b + NEAR]))


def _en_day(word: str, wd: int) -> str:
    full = _EN_DAYS[wd]
    out = full if len(word.rstrip(".")) > 4 else full[:3]
    return out.upper() if word.isupper() else (out.lower() if word.islower() else out)


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", s)


def fix(reply: str, question: str, today: date | None = None) -> tuple[str, list[tuple[str, str]]]:
    """today 缺省 = 用户时区的今天（settings.timezone）。"""
    if not reply or not re.search(r"周|星期|礼拜|mon|tue|wed|thu|fri|sat|sun", reply, re.I):
        return reply, []
    today = today or datetime.now(zone(None)).date()
    hint = _year_hint(reply, question)
    q = _norm(question or "")
    edits: list[tuple[int, int, str, str]] = []  # (start, end, 原文, 新文)

    def consider(mt: re.Match, real: date | None, stated: int, span: tuple[int, int], new_word: str) -> None:
        a, b = mt.span()
        if real is None or real.weekday() == stated:
            return
        if _RANGE_AFTER.match(reply, b) or _norm(mt.group(0)) in q or _quoted(reply, a, b) or _disputed(reply, a, b):
            return
        if any(not (b <= s or a >= e) for s, e, _, _ in edits):
            return
        edits.append((span[0], span[1], reply[span[0]:span[1]], new_word))

    for rx in (CN_AFTER, CN_BEFORE):
        for mt in rx.finditer(reply):
            g = mt.groupdict()
            y = g["y"] or g["y2"]
            m, d = int(g["m"] or g["m2"] or g["m3"]), int(g["d"] or g["d2"] or g["d3"])
            year = int(y) if y else _pick_year(m, d, today, hint)
            real = _real(year, m, d)
            stated = "一二三四五六日".find(g["wd"]) if g["wd"] not in "天" else 6
            if real is not None:
                consider(mt, real, stated, mt.span("wd"), WEEKDAYS[real.weekday()])
    for rx in (EN_BEFORE, EN_AFTER):
        for mt in rx.finditer(reply):
            m, d = _MONTHS[mt["emon"].lower().rstrip(".")], int(mt["ed"])
            year = int(mt["ey"]) if mt["ey"] else _pick_year(m, d, today, hint)
            real = _real(year, m, d)
            word = mt["ewd"]
            stated = next(i for i, n in enumerate(_EN_DAYS) if n.lower().startswith(word.lower()[:3]))
            if real is not None:
                consider(mt, real, stated, mt.span("ewd"), _en_day(word, real.weekday()))
    if not edits:
        return reply, []
    out, last, changes = [], 0, []
    for s, e, old, new in sorted(edits):
        out += [reply[last:s], new]
        last = e
        changes.append((old, new))
    out.append(reply[last:])
    return "".join(out), changes
