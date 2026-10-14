"""给模型用的“钟表”：查现在几点、换算时区、算相对日期的唯一规则（v1.99，大脑 ao）。

对标 Hark 公开行为：助手遇到“明天”“下周一”“10 天后”不自己心算，而是让工具出准确的日期和星期；
跨时区的时间按当天的夏令时换算。三家参考（deepseek-harness / Codex / Gemini CLI）都只在上下文里放
一句“今天是…”（Codex environment_context 的 current_date + timezone），没有日期计算工具——这里自写规则。

- zone(name)：时区名 → ZoneInfo。认 IANA 名（大小写不敏感）、常用中文城市名、UTC±N、几个常见缩写；
  认不出时给最像的几个名字（ClockError），不瞎猜。
- now_text(tz)：现在 = 日期 + 星期 + 时刻 + UTC 偏移 + 是否夏令时。
- convert(time, src, dst, on)：把 src 时区某天的钟点换到 dst。偏移按那一天算（夏令时前后不同）；
  那一刻在 src 不存在（春季拨快跳过的一小时）→ 报错说清；出现两次（秋季拨回）→ 按第一次算并注明。
- resolve(expression, days, tz)：今天 + days 天 → 日期和星期。expression 是能一眼看懂的写法时
  （明天、后天、3 天后、2 周前、下周三、这周五、上周日……）按写法自己算一遍；和模型给的天数不一致时
  以写法为准并注明（模型最常见的错就是星期几数错一天）。认不出的写法照模型给的天数算。
  “N 个月后”按日历月加（月底钳到当月最后一天），也以写法为准。

一周从周一开始（中文习惯）：“下周三”= 下一个周一起的那一周的周三；“这周五”= 本周的周五（可能已过去）。
"""
from __future__ import annotations

import calendar
import difflib
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from functools import lru_cache
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

from .config import settings

WEEKDAYS = "一二三四五六日"
MAX_DAYS = 36_600     # ±100 年：再远就是写错了
SUGGEST = 3

# 常用叫法 → IANA。只收一眼不会错的；其余让模型传 IANA 名。
ALIASES = {
    "北京": "Asia/Shanghai", "上海": "Asia/Shanghai", "中国": "Asia/Shanghai", "北京时间": "Asia/Shanghai",
    "深圳": "Asia/Shanghai", "广州": "Asia/Shanghai", "成都": "Asia/Shanghai", "杭州": "Asia/Shanghai",
    "香港": "Asia/Hong_Kong", "台北": "Asia/Taipei", "澳门": "Asia/Macau",
    "东京": "Asia/Tokyo", "日本": "Asia/Tokyo", "首尔": "Asia/Seoul", "韩国": "Asia/Seoul",
    "新加坡": "Asia/Singapore", "曼谷": "Asia/Bangkok", "迪拜": "Asia/Dubai", "新德里": "Asia/Kolkata", "印度": "Asia/Kolkata",
    "伦敦": "Europe/London", "英国": "Europe/London", "巴黎": "Europe/Paris", "柏林": "Europe/Berlin",
    "莫斯科": "Europe/Moscow", "纽约": "America/New_York", "华盛顿": "America/New_York", "波士顿": "America/New_York",
    "芝加哥": "America/Chicago", "丹佛": "America/Denver", "洛杉矶": "America/Los_Angeles",
    "旧金山": "America/Los_Angeles", "西雅图": "America/Los_Angeles", "温哥华": "America/Vancouver",
    "多伦多": "America/Toronto", "悉尼": "Australia/Sydney", "墨尔本": "Australia/Melbourne", "奥克兰": "Pacific/Auckland",
    "UTC": "UTC", "GMT": "UTC", "Z": "UTC", "CST": "Asia/Shanghai",  # CST 在中文语境里几乎总是中国标准时间
    "JST": "Asia/Tokyo", "KST": "Asia/Seoul", "HKT": "Asia/Hong_Kong", "SGT": "Asia/Singapore",
    "PST": "America/Los_Angeles", "PDT": "America/Los_Angeles", "PT": "America/Los_Angeles",
    "EST": "America/New_York", "EDT": "America/New_York", "ET": "America/New_York",
    "CET": "Europe/Paris", "CEST": "Europe/Paris", "BST": "Europe/London",
}
_OFFSET = re.compile(r"^(?:UTC|GMT)\s*([+-])\s*(\d{1,2})(?::?(\d{2}))?$", re.I)


tzinfo_t = ZoneInfo | timezone


class ClockError(ValueError):
    pass


@lru_cache(maxsize=1)
def _names() -> dict[str, str]:
    return {n.lower(): n for n in available_timezones()}


def zone(name: str | None) -> tzinfo_t:
    """时区名 → tzinfo。空 = 用户的时区（settings.timezone）。"""
    raw = (name or "").strip()
    if not raw:
        return ZoneInfo(settings.timezone)
    key = ALIASES.get(raw) or ALIASES.get(raw.upper()) or ALIASES.get(raw.removesuffix("时间"))
    if key:
        return ZoneInfo(key)
    if m := _OFFSET.match(raw):
        h, mm = int(m[2]), int(m[3] or 0)
        if h > 14 or mm >= 60:
            raise ClockError(f"偏移「{raw}」超出范围（UTC-12 到 UTC+14）")
        delta = timedelta(hours=h, minutes=mm)
        return timezone(delta if m[1] == "+" else -delta, f"UTC{m[1]}{h:02d}:{mm:02d}")
    canon = _names().get(raw.lower().replace(" ", "_"))
    if canon:
        try:
            return ZoneInfo(canon)
        except ZoneInfoNotFoundError:  # 名单里有但系统缺数据（极少）
            pass
    close = difflib.get_close_matches(raw.lower().replace(" ", "_"), list(_names()), n=SUGGEST, cutoff=0.6)
    hint = f"可能是：{'、'.join(_names()[c] for c in close)}" if close else "请传 IANA 时区名，如 Asia/Shanghai、America/New_York"
    raise ClockError(f"不认识时区「{raw}」。{hint}")



def zone_name(tz: tzinfo_t) -> str:
    return getattr(tz, "key", None) or str(tz)


def _offset(dt: datetime) -> str:
    off = dt.utcoffset() or timedelta(0)
    sign = "-" if off < timedelta(0) else "+"
    mins = abs(int(off.total_seconds())) // 60
    return f"UTC{sign}{mins // 60:02d}:{mins % 60:02d}"


def weekday(d: date) -> str:
    return f"周{WEEKDAYS[d.weekday()]}"


def day_text(d: date) -> str:
    return f"{d.isoformat()} {weekday(d)}"


NEAR = {-1: "昨天", 0: "今天", 1: "明天", 2: "后天"}


def near_day(d: date, today: date) -> str:
    """离今天近的日子给相对说法 + 星期（“今天 周三”），远的只给星期——工具结果里的日期让模型照抄，不心算。"""
    rel = NEAR.get((d - today).days)
    return f"{rel} {weekday(d)}" if rel else weekday(d)


def _dst_note(dt: datetime) -> str:
    if not isinstance(dt.tzinfo, ZoneInfo):
        return ""
    dst = dt.dst()
    if dst is None:
        return ""
    # 这个时区一年里有没有夏令时：看 1 月和 7 月偏移是否不同
    y = dt.year
    jan = datetime(y, 1, 1, 12, tzinfo=dt.tzinfo).utcoffset()
    jul = datetime(y, 7, 1, 12, tzinfo=dt.tzinfo).utcoffset()
    if jan == jul:
        return ""
    return "，夏令时" if dst else "，不在夏令时"


def now_text(tz_name: str | None = None, now: datetime | None = None) -> tuple[str, str]:
    """(给模型的一句, 时间线摘要)。"""
    tz = zone(tz_name)
    n = (now or datetime.now(timezone.utc)).astimezone(tz)
    text = f"现在是 {day_text(n.date())} {n:%H:%M:%S}（{zone_name(tz)}，{_offset(n)}{_dst_note(n)}）。"
    return text, f"{n:%m-%d} {weekday(n.date())} {n:%H:%M} {zone_name(tz)}"


def _parse_time(s: str) -> time:
    m = re.fullmatch(r"\s*(\d{1,2})[:：](\d{2})(?::(\d{2}))?\s*", s or "")
    if not m or int(m[1]) > 23 or int(m[2]) > 59 or int(m[3] or 0) > 59:
        raise ClockError(f"时间「{s}」要写成 24 小时制 HH:MM，如 09:30、21:00")
    return time(int(m[1]), int(m[2]), int(m[3] or 0))


def _parse_date(s: str) -> date:
    try:
        return date.fromisoformat((s or "").strip())
    except ValueError:
        raise ClockError(f"日期「{s}」要写成 YYYY-MM-DD，如 2026-07-15") from None


def _day_shift(a: date, b: date) -> str:
    n = (b - a).days
    return {0: "", 1: "（第二天）", -1: "（前一天）"}.get(n, f"（{'+' if n > 0 else ''}{n} 天）")


@dataclass
class Conversion:
    text: str
    detail: str


def convert(t: str, src: str, dst: str, on: str | None = None, now: datetime | None = None) -> Conversion:
    clock = _parse_time(t)
    stz, dtz = zone(src), zone(dst)
    day = _parse_date(on) if on else (now or datetime.now(timezone.utc)).astimezone(stz).date()
    wall = datetime.combine(day, clock, tzinfo=stz)
    notes = []
    if isinstance(stz, ZoneInfo):
        back = wall.astimezone(timezone.utc).astimezone(stz)
        if back.replace(tzinfo=None) != wall.replace(tzinfo=None):  # 春季拨快跳过的那段钟点
            raise ClockError(f"{day.isoformat()} {clock:%H:%M} 在 {zone_name(stz)} 不存在（那天夏令时开始，钟表跳过了这段），"
                             f"请改成 {back:%H:%M} 或别的时刻")
        if wall.replace(fold=1).utcoffset() != wall.utcoffset():
            notes.append(f"这一刻在 {zone_name(stz)} 出现两次（夏令时结束、钟表拨回），按第一次算")
    out = wall.astimezone(dtz)
    src_s = f"{day_text(day)} {clock:%H:%M}（{zone_name(stz)}，{_offset(wall)}）"
    dst_s = f"{day_text(out.date())} {out:%H:%M}（{zone_name(dtz)}，{_offset(out)}）{_day_shift(day, out.date())}"
    text = f"{src_s} = {dst_s}。" + ("".join(f"\n注意：{n}。" for n in notes))
    if not on:
        text += f"\n（没给日期，按 {zone_name(stz)} 的今天 {day.isoformat()} 算；别的日子夏令时可能不同，请带 date。）"
    detail = f"{clock:%H:%M} {zone_name(stz)} → {out:%H:%M} {zone_name(dtz)}{_day_shift(day, out.date())}"
    return Conversion(text, detail)


# ---------- 相对日期 ----------

_CN_NUM = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
_WD = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6, "七": 6}
_EN_WD = {d.lower(): i for i, d in enumerate(calendar.day_name)}
_FIXED = {
    "今天": 0, "今日": 0, "明天": 1, "明日": 1, "后天": 2, "大后天": 3, "昨天": -1, "昨日": -1, "前天": -2, "大前天": -3,
    "today": 0, "tomorrow": 1, "yesterday": -1, "the day after tomorrow": 2, "the day before yesterday": -2,
}


def _num(s: str) -> int | None:
    s = s.strip()
    if s.isdigit():
        return int(s)
    if not s or any(c not in _CN_NUM for c in s):
        return None
    if s == "十":
        return 10
    if "十" in s:  # 十五、二十、二十三
        head, _, tail = s.partition("十")
        return (_CN_NUM[head] if head else 1) * 10 + (_CN_NUM[tail] if tail else 0)
    return _CN_NUM[s] if len(s) == 1 else None


def _add_months(d: date, n: int) -> date:
    y, m = divmod(d.month - 1 + n, 12)
    y += d.year
    return date(y, m + 1, min(d.day, calendar.monthrange(y, m + 1)[1]))


def expected(expression: str, today: date) -> tuple[date, str] | None:
    """能一眼看懂的写法自己算：(日期, 怎么算的)。认不出 → None。"""
    e = re.sub(r"\s+", " ", (expression or "").strip().lower()).strip("。.?？!！")
    e_cn = e.replace(" ", "").replace("星期", "周").replace("礼拜", "周")
    if e in _FIXED or e_cn in _FIXED:
        n = _FIXED.get(e, _FIXED.get(e_cn))
        return today + timedelta(days=n), f"{n:+d} 天"
    # N 天/周/个月 后/前（含 “以后”“之后”“以前”“之前”）
    if m := re.fullmatch(r"(\d+|[零〇一二两三四五六七八九十]+)(天|日|周|个星期|星期|个礼拜|个月|月|年)(以后|之后|后|以前|之前|前)", e_cn):
        n = _num(m[1])
        if n is not None:
            sign = -1 if "前" in m[3] else 1
            unit = m[2]
            if unit in ("天", "日"):
                return today + timedelta(days=sign * n), f"{sign * n:+d} 天"
            if unit in ("周", "个星期", "星期", "个礼拜"):
                return today + timedelta(days=sign * 7 * n), f"{sign * 7 * n:+d} 天（{n} 周）"
            if unit == "年":
                return _add_months(today, sign * 12 * n), f"{'+' if sign > 0 else '-'}{n} 年（按日历）"
            return _add_months(today, sign * n), f"{'+' if sign > 0 else '-'}{n} 个月（按日历月）"
    if m := re.fullmatch(r"in (\d+) (day|days|week|weeks)", e):
        n = int(m[1]) * (7 if m[2].startswith("week") else 1)
        return today + timedelta(days=n), f"{n:+d} 天"
    if m := re.fullmatch(r"(\d+) (day|days|week|weeks) (ago|later|from now|from today)", e):
        n = int(m[1]) * (7 if m[2].startswith("week") else 1) * (-1 if m[3] == "ago" else 1)
        return today + timedelta(days=n), f"{n:+d} 天"
    # 下周三 / 这周五 / 本周日 / 上周一 / 下下周二（周一开始的自然周）
    if m := re.fullmatch(r"(下下|下|这|本|今|上上|上)?个?周([一二三四五六日天七])", e_cn):
        week = {"下下": 2, "下": 1, "这": 0, "本": 0, "今": 0, "上": -1, "上上": -2, None: None}[m[1]]
        if week is None:  # 只说“周三”：可以是这周或下周，交给模型
            return None
        monday = today - timedelta(days=today.weekday())
        d = monday + timedelta(days=7 * week + _WD[m[2]])
        return d, f"{'本' if week == 0 else ('下' * week if week > 0 else '上' * -week)}周{m[2]}"
    return None


@dataclass
class Resolved:
    date: date
    text: str
    detail: str
    corrected: bool = False


def resolve(expression: str, days: int, tz_name: str | None = None, now: datetime | None = None) -> Resolved:
    if not isinstance(days, int) or isinstance(days, bool):
        raise ClockError("days_from_today 要是整数（今天 0，明天 1，昨天 -1）")
    if abs(days) > MAX_DAYS:
        raise ClockError(f"days_from_today={days} 太远了（最多 ±{MAX_DAYS}）")
    tz = zone(tz_name)
    today = (now or datetime.now(timezone.utc)).astimezone(tz).date()
    target = today + timedelta(days=days)
    guess = expected(expression, today)
    corrected = False
    how = f"{days:+d} 天"
    if guess is not None:
        if guess[0] != target:
            corrected = True
            target = guess[0]
        how = guess[1]
    label = (expression or "").strip() or f"{days:+d} 天"
    text = f"「{label}」= {day_text(target)}（今天 {day_text(today)}，{how}；{zone_name(tz)}）。"
    if corrected:
        text += f"\n注意：你给的 days_from_today={days} 和「{label}」对不上，已按写法算成 {(target - today).days:+d} 天。"
    if guess is None and not re.search(r"\d|[今明后昨前天周月年]|day|week|month|year", label.lower()):
        text += "\n（认不出这个写法，按你给的天数算的；请确认天数对应用户说的日子。）"
    return Resolved(target, text, f"{label} → {target:%m-%d} {weekday(target)}", corrected)
