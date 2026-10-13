"""记录面板（v2.55，对标 Hark 面板的 log：“记一笔：今天跑了 5 公里”）——“用户自己报的数据记在面板上”的唯一规则。

面板是 kind=log、output=panel 的定时任务：每一笔存在 panel_entries，面板内容由这里按笔算出来（今天 / 近 7 天 / 连续几天 /
最近几笔），不调模型、不花 token。cron 每天零点过一分重算一次，让“今天”翻篇；记一笔、删一笔当场重算。
- 记一笔前先看这个面板一直记不记数量：以前的笔都有数量、这次没给 → 不记，回一句“先问用户这次多少”（只问那一个值）。
- 单位跟着面板走：给了不同单位按各自单位分开合计，不换算。
- 面板移除（panel_trash）时笔留着，revive 后 adopt 到新任务；30 天后清卡时 drop；删任务（task_store）时 drop。
"""
import math
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import delete, func, select, update

from .blocks import text_to_blocks
from .config import settings
from .models import HomeCard, PanelEntry, ScheduledTask

KIND = "log"
CRON = "1 0 * * *"      # 每天零点过一分：今天翻篇
TEXT_MAX = 200
UNIT_MAX = 16
AMOUNT_MAX = 1e9
ENTRIES_MAX = 5000      # 一个面板最多几笔（够记十几年的每日一笔）
RECENT_SHOWN = 8        # 面板上列最近几笔
LISTED = 20             # 给模型 list 的笔数
FUTURE_SLACK = timedelta(minutes=10)
PAST_MAX = timedelta(days=366)
STATS_MAX = 6           # StatsBlock 上限


class LogError(ValueError):
    """记不了（原因是给模型看的中文）。"""


def is_log(task: ScheduledTask | None) -> bool:
    return task is not None and task.kind == KIND


def _tz() -> ZoneInfo:
    return ZoneInfo(settings.timezone)


def _aware(t: datetime) -> datetime:
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def _num(x: float) -> str:
    """5.0 → 5；2.25 → 2.25；12345.678 → 12345.68。"""
    if float(x).is_integer():
        return str(int(x))
    return f"{x:.2f}".rstrip("0").rstrip(".")


def _qty(amount: float | None, unit: str | None) -> str:
    if amount is None:
        return "—"
    u = unit or ""
    return f"{u}{_num(amount)}" if u in ("¥", "$", "€", "£") else f"{_num(amount)} {u}".strip()


def clean(text: str | None, amount: object, unit: str | None) -> tuple[str, float | None, str | None]:
    """一笔的内容是否成立：文字 1–TEXT_MAX 字，数量是有限数，单位 ≤ UNIT_MAX 字。不成立 → LogError。"""
    text = " ".join((text or "").split())
    if not text:
        raise LogError("text 不能空：写这一笔是什么（如“晨跑”“午饭 麻辣烫”）。")
    if len(text) > TEXT_MAX:
        raise LogError(f"text 太长（{len(text)} 字，上限 {TEXT_MAX}）：一笔写一句。")
    if amount is not None:
        try:
            amount = float(amount)
        except (TypeError, ValueError):
            raise LogError(f"amount 要是数字，收到 {amount!r}；单位放 unit。")
        if not math.isfinite(amount) or abs(amount) >= AMOUNT_MAX:
            raise LogError("amount 不是合理的数字。")
    unit = (unit or "").strip() or None
    if unit and len(unit) > UNIT_MAX:
        raise LogError(f"unit 太长（上限 {UNIT_MAX} 字）：只写单位，如 公里 / 毫升 / ¥。")
    if unit and amount is None:
        unit = None
    return text, amount, unit


def when(at: str | None, now: datetime | None = None) -> datetime:
    """这笔的时刻：不给 = 现在；给了按用户时区解析（“2026-10-13 07:30”或只有日期 = 当天中午）。未来 / 一年前 → LogError。"""
    now = now or datetime.now(timezone.utc)
    if not (at or "").strip():
        return now
    raw = at.strip().replace("/", "-")
    try:
        t = datetime.fromisoformat(raw + (" 12:00" if len(raw) == 10 else ""))
    except ValueError:
        raise LogError("at 格式是 YYYY-MM-DD 或 YYYY-MM-DD HH:MM（用户时区）；就是现在就别传。")
    t = (t if t.tzinfo else t.replace(tzinfo=_tz())).astimezone(timezone.utc)
    if t > now + FUTURE_SLACK:
        raise LogError("at 在未来：记录只记已经发生的事（要提醒用 schedule_task）。")
    if t < now - PAST_MAX:
        raise LogError("at 太早（超过一年前）。")
    return t


async def panels(db) -> list[ScheduledTask]:
    """现有的记录面板（卡还在 Home 上的），新的在前。"""
    rows = (await db.scalars(select(ScheduledTask).where(ScheduledTask.kind == KIND)
                             .order_by(ScheduledTask.created_at.desc()))).all()
    return list(rows)


async def find(db, id: str | None, title: str | None) -> ScheduledTask | None:
    """按卡片 id / 任务 id / 标题找记录面板；都没给且只有一个 → 就是它。多个对不上 → LogError（列出来）。没有 → None。"""
    rows = await panels(db)
    if id:
        card = await db.get(HomeCard, id)
        tid = card.task_id if card is not None else id
        hit = next((t for t in rows if t.id == tid), None)
        if hit is None:
            raise LogError(f"{id} 不是记录面板。" + listing(rows))
        return hit
    if title:
        want = "".join(title.split()).casefold()
        exact = [t for t in rows if "".join(t.name.split()).casefold() == want]
        if exact:
            return exact[0]
        near = [t for t in rows if want in "".join(t.name.split()).casefold()
                or "".join(t.name.split()).casefold() in want]
        if len(near) == 1:
            return near[0]
        if len(near) > 1:
            raise LogError(f"「{title}」对上好几个记录面板，给 id。" + listing(rows))
        return None
    if len(rows) == 1:
        return rows[0]
    if rows:
        raise LogError("有好几个记录面板，给 id 或 title。" + listing(rows))
    return None


def listing(rows: list[ScheduledTask]) -> str:
    return (" 现有记录面板：" + "；".join(f"「{t.name}」id={t.id}" for t in rows)) if rows else " 还没有记录面板。"


async def create(db, title: str, about: str | None = None) -> ScheduledTask:
    """新建记录面板（不 commit 之外不跑模型）：任务 + 卡，内容当场算。"""
    title = " ".join((title or "").split())[:40]
    if not title:
        raise LogError("新建记录面板要给 title（几个字，如“跑步”“喝水”“记账”）。")
    task = ScheduledTask(name=title, prompt=(about or "").strip()[:500] or f"记录：{title}", cron=CRON,
                         output="panel", kind=KIND)
    db.add(task)
    await db.flush()
    card = HomeCard(kind="panel", title=title, task_id=task.id, blocks=[])
    db.add(card)
    card.blocks = await render(db, task)
    return task


async def _entries(db, task_id: str, limit: int | None = None) -> list[PanelEntry]:
    q = select(PanelEntry).where(PanelEntry.task_id == task_id).order_by(PanelEntry.at.desc(), PanelEntry.created_at.desc())
    return list((await db.scalars(q.limit(limit) if limit else q)).all())


async def count(db, task_id: str) -> int:
    return await db.scalar(select(func.count()).select_from(PanelEntry).where(PanelEntry.task_id == task_id)) or 0


async def needs_amount(db, task: ScheduledTask) -> str | None:
    """这个面板一直记数量吗：最近几笔都有数量 → 返回最常用的单位（可能是 ""）；否则 None。"""
    recent = await _entries(db, task.id, 5)
    if not recent or any(e.amount is None for e in recent):
        return None
    units = [e.unit or "" for e in recent]
    return max(set(units), key=units.count)


async def add(db, task: ScheduledTask, text: str | None, amount: object = None, unit: str | None = None,
              at: str | None = None, now: datetime | None = None) -> tuple[PanelEntry, str]:
    """记一笔并重算面板（commit）。返回 (这笔, 给模型的回执)。缺一直记的数量 → LogError（只问那一个值）。"""
    text, amount, unit = clean(text, amount, unit)
    t = when(at, now)
    if amount is None and (usual := await needs_amount(db, task)) is not None:
        raise LogError(f"「{task.name}」每笔都记了数量（{usual or '数字'}），这次没给：先问用户这次是多少，只问这一个，拿到再记。")
    if await count(db, task.id) >= ENTRIES_MAX:
        raise LogError(f"「{task.name}」已经记了 {ENTRIES_MAX} 笔，到上限了：删掉旧的或另开一个面板。")
    if amount is not None and unit is None:
        unit = await _usual_unit(db, task.id)
    entry = PanelEntry(task_id=task.id, at=t, text=text, amount=amount, unit=unit)
    db.add(entry)
    await db.flush()
    await refresh_card(db, task)
    await db.commit()
    return entry, await receipt(db, task, entry)


async def _usual_unit(db, task_id: str) -> str | None:
    """数量没带单位：沿用这个面板上一笔的单位（“又跑了 3” → 3 公里）。"""
    last = await db.scalar(select(PanelEntry).where(PanelEntry.task_id == task_id, PanelEntry.amount.is_not(None))
                           .order_by(PanelEntry.at.desc()).limit(1))
    return last.unit if last is not None else None


async def remove(db, task: ScheduledTask, entry_id: str | None) -> PanelEntry:
    """删一笔：entry_id 或 "last"（最近记的那笔，按记录时刻）。没有 → LogError。commit。"""
    if not entry_id or entry_id == "last":
        entry = await db.scalar(select(PanelEntry).where(PanelEntry.task_id == task.id)
                                .order_by(PanelEntry.created_at.desc()).limit(1))
    else:
        entry = await db.get(PanelEntry, entry_id)
        entry = entry if entry is not None and entry.task_id == task.id else None
    if entry is None:
        raise LogError(f"「{task.name}」里没有这一笔，先用 action=list 看 id。")
    await db.delete(entry)
    await db.flush()
    await refresh_card(db, task)
    await db.commit()
    return entry


def _day(t: datetime) -> datetime:
    return _aware(t).astimezone(_tz()).date()


def _sum(rows: list[PanelEntry], unit: str) -> float:
    return sum(e.amount or 0 for e in rows if e.amount is not None and (e.unit or "") == unit)


def _streak(days: set, today) -> int:
    """连续有记录的天数：今天还没记就从昨天往回数（今天还有机会）。"""
    d = today if today in days else today - timedelta(days=1)
    n = 0
    while d in days:
        n += 1
        d -= timedelta(days=1)
    return n


async def summary(db, task: ScheduledTask, now: datetime | None = None) -> dict:
    """面板 / 回执 / read 共用的数字：今天、近 7 天（按单位）、连续天数、总笔数。"""
    now = now or datetime.now(timezone.utc)
    today = _day(now)
    rows = await _entries(db, task.id)
    week_from = today - timedelta(days=6)
    today_rows = [e for e in rows if _day(e.at) == today]
    week_rows = [e for e in rows if week_from <= _day(e.at) <= today]
    units: list[str] = []
    for e in rows:  # 单位按最近用的先后
        if e.amount is not None and (e.unit or "") not in units:
            units.append(e.unit or "")
    return {"rows": rows, "today": today_rows, "week": week_rows, "units": units,
            "streak": _streak({_day(e.at) for e in rows}, today), "total": len(rows)}


async def render(db, task: ScheduledTask, now: datetime | None = None) -> list[dict]:
    """面板内容：数字卡（有数量：每个单位 今天 + 近 7 天；没数量：今天几笔 + 近 7 天几笔）+ 连续天数 + 最近几笔的表。"""
    s = await summary(db, task, now)
    if not s["rows"]:
        return text_to_blocks(f"还没有记录。在聊天里说一句就记上，比如“{task.name}：……”。")
    stats: list[dict] = []
    for u in s["units"][:2]:
        stats.append({"label": "今天", "value": _qty(_sum(s["today"], u), u)})
        stats.append({"label": "近 7 天", "value": _qty(_sum(s["week"], u), u),
                      "note": f"日均 {_qty(_sum(s['week'], u) / 7, u)}"})
    if not s["units"]:
        stats += [{"label": "今天", "value": f"{len(s['today'])} 笔"}, {"label": "近 7 天", "value": f"{len(s['week'])} 笔"}]
    stats.append({"label": "连续", "value": f"{s['streak']} 天", "note": f"共 {s['total']} 笔"})
    tz = _tz()
    rows = [[_aware(e.at).astimezone(tz).strftime("%m-%d %H:%M"), e.text, _qty(e.amount, e.unit)]
            for e in s["rows"][:RECENT_SHOWN]]
    return [{"type": "stats", "items": stats[:STATS_MAX]},
            {"type": "table", "title": "最近", "columns": ["时间", "内容", "数量"], "rows": rows}]


async def refresh_card(db, task: ScheduledTask, now: datetime | None = None) -> None:
    """把算好的内容写到面板卡上（不 commit）。卡被删了就补一张。"""
    card = await db.scalar(select(HomeCard).where(HomeCard.task_id == task.id, HomeCard.kind == "panel"))
    if card is None:
        card = HomeCard(kind="panel", title=task.name, task_id=task.id, blocks=[])
        db.add(card)
    card.blocks = await render(db, task, now)
    card.updated_at = datetime.now(timezone.utc)


async def receipt(db, task: ScheduledTask, entry: PanelEntry) -> str:
    """给模型的回执：记上了什么 + 今天的合计 + 连续天数（回复用户时说这个，别再编数字）。"""
    s = await summary(db, task)
    today = "；".join(f"今天合计 {_qty(_sum(s['today'], u), u)}" for u in s["units"][:2]) or f"今天第 {len(s['today'])} 笔"
    when_ = _aware(entry.at).astimezone(_tz()).strftime("%m-%d %H:%M")
    return (f"已记到「{task.name}」：{entry.text} {_qty(entry.amount, entry.unit) if entry.amount is not None else ''}".rstrip()
            + f"（{when_}，id={entry.id}）。{today}；连续 {s['streak']} 天，共 {s['total']} 笔。面板已更新。")


async def lines(db, task: ScheduledTask, limit: int = LISTED) -> str:
    """给模型看的最近几笔（带 id，删的时候用）。"""
    rows = await _entries(db, task.id, limit)
    if not rows:
        return f"「{task.name}」还没有记录。"
    tz = _tz()
    out = [f"「{task.name}」（面板任务 id={task.id}）最近 {len(rows)} 笔："]
    out += [f"- id={e.id} {_aware(e.at).astimezone(tz):%Y-%m-%d %H:%M} {e.text} {_qty(e.amount, e.unit) if e.amount is not None else ''}".rstrip()
            for e in rows]
    return "\n".join(out)


async def adopt(db, old_task_id: str | None, new_task_id: str) -> None:
    """面板找回：旧任务名下的笔改指新任务（不 commit）。"""
    if old_task_id:
        await db.execute(update(PanelEntry).where(PanelEntry.task_id == old_task_id).values(task_id=new_task_id))


async def drop(db, task_ids: list[str]) -> None:
    """任务删了 / 移除的面板过期清掉：它的笔一起删（不 commit）。"""
    ids = [t for t in task_ids if t]
    if ids:
        await db.execute(delete(PanelEntry).where(PanelEntry.task_id.in_(ids)))


async def run(db, task: ScheduledTask) -> None:
    """worker 到点 / 手动刷新：只重算内容（今天翻篇），记一条成功的运行。不调模型。commit（task_runs.finish）。"""
    from . import task_runs
    now = datetime.now(timezone.utc)
    record = await task_runs.start(db, task, now)
    task.last_run_at, task.run_requested = now, False
    await refresh_card(db, task, now)
    await db.flush()
    await task_runs.finish(db, task, record, None, None)
