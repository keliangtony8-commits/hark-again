"""“准备今天”的原料：把今天已知的事一次收齐，交给模型写成当日简报（工具 day_overview，技能 prep-my-day）。

只读、不调模型、不联网：一次查库 + 本地计算，所以每次简报只多几百个 token 的输入。
四段，顺序即简报里的优先级：
1. 今天的日程 = 今天排着钟点的报告任务（面板是“随时看”的，不算日程）。时刻由 croniter 按用户时区算，
   与 app/schedule.py 同一套解释；自动暂停的也列出来（今天不会跑，正是要提醒的事）。
2. 主页上等着用户的卡 = 没收起的建议/系统提醒（稍后提醒到今天的也算，标出几点回来）。
3. 收件箱未读报告。
4. 记忆里和今天有关的：写了日期（今天到 WINDOW_DAYS 天内）或写了“周X”且今天正是周X 的记忆。
天气等需要联网的由技能自己 web_search，这里不碰。

exclude_task：正在跑的那个定时任务（早间简报自己）。它不进今天的日程（刚把 last_run_at 记成现在，会显示成“已完成”），
它昨天投递的报告卡也不算未读要提醒的事——简报不该把自己当成今天的一件事。"""
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from croniter import croniter
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from . import schedule
from .clock import WEEKDAYS  # 星期的写法只有 clock 一份
from .blocks import blocks_to_text
from .config import settings
from .models import HomeCard, Memory, ScheduledTask

WINDOW_DAYS = 7      # 记忆里写了日期的，往后看几天
MAX_SLOTS = 3        # 一个任务今天超过这么多次（每小时之类）就合成一行
MAX_MEMORIES = 8
MAX_CARDS = 6
MAX_REPORTS = 5
SNIPPET = 80

_FULL = re.compile(r"(?<!\d)(20\d{2})\s*[-/.年]\s*(\d{1,2})\s*[-/.月]\s*(\d{1,2})\s*[日号]?")
_MONTH_DAY = re.compile(r"(?<![\d年/.-])(\d{1,2})\s*月\s*(\d{1,2})\s*[日号]")
_WEEKDAY = re.compile(r"(?:周|星期|礼拜)([一二三四五六日天])")


def _aware(t: datetime) -> datetime:
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def _snip(text: str) -> str:
    t = re.sub(r"\s+", " ", text).strip()
    return t if len(t) <= SNIPPET else t[:SNIPPET] + "…"


def day_label(d: date) -> str:
    return f"{d.month}月{d.day}日 周{WEEKDAYS[d.weekday()]}"


# ---------- 1. 今天的日程 ----------

def today_slots(task: ScheduledTask, start: datetime) -> list[datetime]:
    """task 在 [start, start+1天) 里的运行时刻（用户时区）。不看 active：自动暂停的也要列出来。"""
    end = start + timedelta(days=1)
    if task.run_at is not None:
        at = _aware(task.run_at).astimezone(start.tzinfo)
        return [at] if start <= at < end else []
    if not croniter.is_valid(task.cron or ""):
        return []
    it, out = croniter(task.cron, start - timedelta(seconds=1)), []
    while len(out) <= 24 * 60:  # 每分钟一次也有上限
        at = it.get_next(datetime)
        if at >= end:
            break
        out.append(at)
    return out


def _slot_state(task: ScheduledTask, slot: datetime, now: datetime) -> str:
    last = _aware(task.last_run_at) if task.last_run_at else None
    if last is not None and last >= slot:
        return "失败了" if task.last_status == "error" else "已完成"
    if task.run_requested:
        return "正在跑"
    return "到点了，马上跑" if slot <= now else "待运行"


def agenda_line(task: ScheduledTask, slots: list[datetime], now: datetime) -> str:
    hm = lambda t: t.strftime("%H:%M")
    if task.paused_reason == "failures":
        return f"- {hm(slots[0])}「{task.name}」连续失败 {task.fail_streak} 次已自动暂停，今天不会跑（任务 id={task.id}）"
    if len(slots) > MAX_SLOTS:
        done = sum(1 for s in slots if s <= now)
        upcoming = next((s for s in slots if s > now), None)
        tail = f"，下一次 {hm(upcoming)}" if upcoming else "，今天的都过了"
        bad = "，上次失败" if task.last_status == "error" else ""
        return f"- {hm(slots[0])}–{hm(slots[-1])}「{task.name}」今天 {len(slots)} 次，已过 {done} 次{tail}{bad}"
    current = max((s for s in slots if s <= now), default=slots[0])
    times = "、".join(hm(s) for s in slots)
    return f"- {times}「{task.name}」{_slot_state(task, current, now)}"


async def _agenda(db: AsyncSession, start: datetime, now: datetime, exclude: str | None = None) -> list[str]:
    tasks = (await db.scalars(select(ScheduledTask).where(ScheduledTask.output == "report"))).all()
    rows: list[tuple[datetime, str]] = []
    for t in tasks:
        if t.id == exclude:
            continue
        if not (t.active or t.paused_reason == "failures" or schedule.is_done(t)):
            continue  # 用户手动停掉的不算今天的事
        slots = today_slots(t, start)
        if slots:
            rows.append((slots[0], agenda_line(t, slots, now)))
    return [line for _, line in sorted(rows, key=lambda r: r[0])]


# ---------- 2/3. 主页 ----------

def card_line(card: HomeCard, today: date, tz: ZoneInfo) -> str | None:
    """一张没收起的建议/提醒卡；稍后提醒到别的日子的 → None（今天不打扰）。"""
    tag = ("需要用户亲自处理" if not card.action_prompt else
           f"你提议的，按钮“{card.action_label or '去做'}”" if card.origin == "agent" else "建议")
    if card.conversation_id and card.origin == "agent":
        tag += "，用户已点开始做"
    if card.snoozed_until is not None:
        back = _aware(card.snoozed_until).astimezone(tz)
        if back.date() != today:
            return None
        tag += f"，稍后提醒，今天 {back:%H:%M} 回来"
    why = _snip(blocks_to_text(card.blocks or []))
    return f"- id={card.id}「{card.title}」{tag}" + (f"：{why}" if why else "")


async def _cards(db: AsyncSession, today: date, tz: ZoneInfo,
                 exclude: str | None = None) -> tuple[list[str], list[str], int]:
    q = select(HomeCard).where(HomeCard.dismissed.is_(False), HomeCard.kind.in_(("action", "report")))
    if exclude:  # 任务自己的报告卡；它的失败提醒（system alert 也挂 task_id）照样列——失败正是要说的
        q = q.where(or_(HomeCard.task_id.is_(None), HomeCard.task_id != exclude, HomeCard.kind != "report"))
    rows = (await db.scalars(q.order_by(HomeCard.updated_at.desc()))).all()
    actions = [l for c in rows if c.kind == "action" for l in [card_line(c, today, tz)] if l]
    unread = [c for c in rows if c.kind == "report" and c.unread]
    reports = [f"- 「{c.title}」{_aware(c.updated_at).astimezone(tz):%m-%d %H:%M}" + (f"：{c.gist}" if c.gist else "")
               for c in unread[:MAX_REPORTS]]
    return actions[:MAX_CARDS], reports, len(unread)


# ---------- 4. 记忆 ----------

def _safe_date(y: int, m: int, d: int) -> date | None:
    try:
        return date(y, m, d)
    except ValueError:
        return None


def memory_dates(content: str, today: date) -> list[date]:
    """记忆里写到的、落在 [今天, 今天+WINDOW_DAYS] 的日期。只写月日的按今年，已过就看明年。"""
    found: list[date] = []
    spans: list[tuple[int, int]] = []
    for m in _FULL.finditer(content):
        spans.append(m.span())
        d = _safe_date(int(m[1]), int(m[2]), int(m[3]))
        if d:
            found.append(d)
    for m in _MONTH_DAY.finditer(content):
        if any(a <= m.start() < b for a, b in spans):
            continue
        d = _safe_date(today.year, int(m[1]), int(m[2]))
        if d and d < today:
            d = _safe_date(today.year + 1, int(m[1]), int(m[2]))
        if d:
            found.append(d)
    return sorted({d for d in found if 0 <= (d - today).days <= WINDOW_DAYS})


def mentions_weekday(content: str, today: date) -> bool:
    want = WEEKDAYS[today.weekday()]
    return any((m[1] if m[1] != "天" else "日") == want for m in _WEEKDAY.finditer(content))


def memory_line(mem: Memory, today: date) -> tuple[int, str] | None:
    """(排序键, 行)：带日期的按距今天数，只写“周X”的排在当天之后。"""
    dates = memory_dates(mem.content, today)
    if dates:
        days = (dates[0] - today).days
        when = "今天" if days == 0 else "明天" if days == 1 else f"{days} 天后（{day_label(dates[0])}）"
        return days, f"- {when}：{_snip(mem.content)}（记忆 #{mem.id}）"
    if mentions_weekday(mem.content, today):
        return 0, f"- 今天是周{WEEKDAYS[today.weekday()]}：{_snip(mem.content)}（记忆 #{mem.id}）"
    return None


async def _memories(db: AsyncSession, today: date) -> list[str]:
    mems = (await db.scalars(select(Memory).order_by(Memory.updated_at.desc()))).all()
    hits = sorted((h for m in mems for h in [memory_line(m, today)] if h), key=lambda h: h[0])
    return [line for _, line in hits[:MAX_MEMORIES]]


# ---------- 汇总 ----------

@dataclass
class DayBrief:
    now: datetime
    agenda: list[str] = field(default_factory=list)
    cards: list[str] = field(default_factory=list)
    reports: list[str] = field(default_factory=list)
    unread: int = 0
    memories: list[str] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return not (self.agenda or self.cards or self.unread or self.memories)

    def text(self) -> str:
        n = self.now
        out = [f"今天 {n:%Y-%m-%d} 周{WEEKDAYS[n.weekday()]}，现在 {n:%H:%M}（{settings.timezone}）。"]
        out += ["", "【今天的日程】（定时任务，按钟点）", *(self.agenda or ["- 今天没有排定的任务"])]
        out += ["", "【主页上等着用户的卡】", *(self.cards or ["- 没有"])]
        more = f"（只列最近 {len(self.reports)} 条）" if self.unread > len(self.reports) else ""
        out += ["", f"【收件箱】未读 {self.unread} 条{more}", *self.reports]
        out += ["", f"【记忆里和今天有关的】（写了今天起 {WINDOW_DAYS} 天内的日期，或今天这个星期几）",
                *(self.memories or ["- 没有"])]
        return "\n".join(out)


async def gather(db: AsyncSession, now: datetime | None = None, exclude_task: str | None = None) -> DayBrief:
    tz = ZoneInfo(settings.timezone)
    now = _aware(now or datetime.now(timezone.utc)).astimezone(tz)
    start = datetime.combine(now.date(), time(0), tzinfo=tz)
    cards, reports, unread = await _cards(db, now.date(), tz, exclude_task)
    return DayBrief(now=now, agenda=await _agenda(db, start, now, exclude_task), cards=cards, reports=reports, unread=unread,
                    memories=await _memories(db, now.date()))
