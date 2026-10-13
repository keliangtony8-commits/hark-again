"""Home：把“要反复看的信息”做成定时刷新的面板（create_panel），以及在对话里管理 Home 上已有的东西（manage_home）：
“我主页上有什么”“把天气面板改成每天 7 点”“删掉那个比分面板”“收件箱那条不用管了”。
面板本质是 output=panel 的定时任务，增删改都走 app/task_store.py（与接口、客户端同一套规则：改名卡片跟着改）；
移除 / 找回面板走 app/panel_trash.py（v2.17：30 天内可 revive）。"""
import asyncio
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from zoneinfo import ZoneInfo

from ... import card_snooze, card_targets, home_offers, panel_trash, schedule, task_brief, task_runs, task_store, task_wall, web_guard
from ...blocks import blocks_to_text
from ...config import settings
from ...db import SessionLocal
from ...models import HomeCard, ScheduledTask, TaskRun
from ..tools import ToolContext, ToolResult, tool
from .display import IMAGE_PROBE_TIMEOUT, probe_image

_KIND = {"action": "建议", "panel": "面板", "report": "收件箱"}
REPORTS_LISTED = 10  # 收件箱只列最近几条，免得把上下文撑大
READ_MAX = 4000      # read 给模型看的面板内容上限（字）
RUNS_LISTED = 10
REFRESH_WAIT = 60    # refresh 等多久看结果（秒；对标 Hark 的“最多等一分钟”）
REFRESH_POLL = 2


@tool("create_panel", "正在创建面板",
      "在 Home 上放一个会自动刷新的面板。prompt 写清楚每次刷新要查什么、怎么展示（它会被独立执行，看不到当前对话）。"
      "cron 按变化快慢取最慢的合理频率：每天变的用每天一次，别用每小时。先用 manage_home list 看看是不是已经有同类面板，有就改它。",
      {"type": "object", "properties": {
          "title": {"type": "string", "description": "面板标题，几个字"},
          "prompt": {"type": "string"},
          "cron": {"type": "string", "description": "5 段 cron，用户时区，如 0 8 * * *"}},
       "required": ["title", "prompt", "cron"]})
async def create_panel(ctx: ToolContext, title: str, prompt: str, cron: str) -> ToolResult:
    try:
        await task_store.create_panel(ctx.db, title=title, prompt=prompt, cron=cron)
    except ValueError as e:
        return ToolResult(str(e))
    return ToolResult(f"面板「{title}」已放到 Home，半分钟内出第一份数据，之后按 {cron} 刷新。")


@tool("offer_on_home", "正在放到主页",
      "在 Home 的“为你准备”里放一张建议卡，提议替用户做一件具体的事（用户点按钮才会做）。"
      "适合：定时任务/简报里发现值得做的事（要回的邮件、快到期的续费、降价了的东西），或聊天中用户说“回头再弄”的事。"
      "一张卡只提一件事；同标题会原地更新不重复；用户没要求的购买/发送也只是提议，不会自动执行。"
      "已经在对话里直接做完的事不要再放。",
      {"type": "object", "properties": {
          "title": {"type": "string", "description": "要做的事，几个字到一句，如“续费校园网”"},
          "reason": {"type": "string", "description": "为什么现在做，一两句具体事实，如“周五到期，今天续还有 9 折”"},
          "prompt": {"type": "string", "description": "用户点按钮后发给助手的完整指令，独立可执行（看不到当前对话），写明对象、网站、数量、价格上限等"},
          "label": {"type": "string", "description": "按钮上的字，12 字以内，说清点了会做什么：帮我续费 / 起草回复 / 查航班；不给就是“去做”"},
          "image": {"type": "string", "description": "可选：卡顶配图，只用这件事本身页面上的真实图片地址（商品图、活动海报），不能自己拼；打不开会被去掉"},
          "url": {"type": "string", "description": "可选：这件事的原页（商品页、邮件网页版、活动页），卡上显示“来源 · 域名”"},
          "open": {"type": "string", "description": "可选：卡上加一颗直达 App 某一页的按钮。" + " / ".join(card_targets.PAGES)
                   + "，或 task:<任务 id>（那个任务的详情）、project:<项目 id>（打开项目，点“去做”开的对话也放进这个项目）。"
                   "只有用户本人能做的事（重新连接账号、存密码）给 open 不给 prompt"}},
       "required": ["title"]}, deferred=True)
async def offer_on_home(ctx: ToolContext, title: str, prompt: str = "", reason: str = "", label: str | None = None,
                        image: str | None = None, url: str | None = None, open: str | None = None) -> ToolResult:
    note = ""
    try:
        target, task_id = await card_targets.resolve(ctx.db, open)
    except ValueError as e:
        return ToolResult(str(e))
    try:
        image = home_offers.clean_url(image, "配图")
    except ValueError:
        image, note = None, " 配图地址不是真实网址，没放图。"
    if image:
        async with web_guard.client(timeout=IMAGE_PROBE_TIMEOUT, follow_redirects=True,
                                     headers={"User-Agent": "Mozilla/5.0 (assistant image check)"}) as client:
            if not await probe_image(client, image):
                image, note = None, " 配图打不开（或不是图片），没放图。"
    try:
        card, status, retired = await home_offers.offer(ctx.db, title, reason, prompt, label, image=image, url=url,
                                                        target=target, task_id=task_id)
    except ValueError as e:
        return ToolResult(str(e))
    button = f"按钮“{card.action_label or '去做'}”" if card.action_prompt else "没有“去做”按钮，用户自己去那页处理"
    out = f"已{'更新' if status == 'updated' else '放到'} Home：「{card.title}」（id={card.id}），{button}。" + note
    if target:
        out += f" 直达：{card_targets.describe(target, task_id)}。"
    if retired:
        out += " 建议太多，收起了较旧的：" + "、".join(f"「{c.title}」" for c in retired) + "。"
    return ToolResult(out)


def _line(card: HomeCard, task: ScheduledTask | None) -> str:
    s = f"- id={card.id} [{_KIND.get(card.kind, card.kind)}]「{card.title}」"
    if card.kind == "panel" and task is not None:
        s += f" · cron {task.cron}" + ("" if task.active else " · 已暂停") + (" · 刷新中" if task.run_requested else "")
        s += f" · 碰壁：{task_wall.label(task.wall)}" if task.wall else (" · 上次刷新失败" if task.last_status == "error" else "")
        s += f" · 刷新指令：{task.prompt[:80]}"
    elif card.kind == "action" and card.origin == home_offers.ORIGIN:
        s += " · 你提议的" + (f" · 按钮“{card.action_label or '去做'}”" if card.action_prompt else "")
        s += (f" · 直达 {card_targets.describe(card.target, card.task_id)}" if card.target else "") + (" · 未读" if card.unread else "")
        s += (" · 有配图" if card.image_url else "") + (f" · 原页 {card.link_url[:80]}" if card.link_url else "")
        if card.conversation_id:
            s += " · 用户已点按钮开始做"
        if card.snoozed_until is not None:
            s += " · 稍后提醒中"
    elif card.snoozed_until is not None:
        at = card_snooze._aware(card.snoozed_until).astimezone(ZoneInfo(settings.timezone))
        s += f" · 稍后提醒于 {at:%m-%d %H:%M}"
    elif card.unread:
        s += " · 未读"
    return s


@tool("manage_home", "正在整理主页",
      "查看和管理 Home 上的卡片。action=list 列出建议、面板、收件箱（带 id）；"
      "read 看一个面板的完整内容和刷新状态（上次结果、下次时间、连续失败、碰壁、是否暂停）；runs 看它最近几次刷新；"
      "refresh 让面板立即刷新并最多等一分钟告诉你结果（用户说面板不对 / 没更新时先 read，再 runs，再 refresh）；update 改面板的 title/prompt/cron（cron 同 create_panel）；"
      "dismiss 拿掉一张卡：建议/收件箱只是隐藏；面板停止刷新、移到“最近移除”（只在用户明确要拿掉时做，别为腾地方或整理主页而删）；"
      "revive 找回最近 30 天移除的面板（list 末尾列着 id）：标题、刷新指令、频率、做法都回来，并马上重新取数据——用户想要回丢掉的面板时先找它，别重建；"
      "snooze 把建议/收件箱先收起，到 until 再放回来并提醒（“明早再提醒我”）；unsnooze 现在就放回来。"
      "id 先用 list 拿到。",
      {"type": "object", "properties": {
          "action": {"type": "string", "enum": ["list", "read", "runs", "refresh", "update", "dismiss", "revive", "snooze", "unsnooze"]},
          "id": {"type": "string", "description": "卡片 id"},
          "title": {"type": "string"},
          "prompt": {"type": "string"},
          "cron": {"type": "string"},
          "until": {"type": "string", "description": "snooze 用：用户时区的 YYYY-MM-DD HH:MM，最多 30 天内"}},
       "required": ["action"]}, deferred=True)
async def manage_home(ctx: ToolContext, action: str, id: str | None = None, title: str | None = None,
                      prompt: str | None = None, cron: str | None = None, until: str | None = None) -> ToolResult:
    db = ctx.db
    if action == "list":
        cards = (await db.scalars(select(HomeCard).where(HomeCard.dismissed.is_(False))
                                  .order_by(HomeCard.updated_at.desc()))).all()
        ids = [c.task_id for c in cards if c.task_id]
        tasks = {t.id: t for t in (await db.scalars(select(ScheduledTask).where(ScheduledTask.id.in_(ids)))).all()} if ids else {}
        out = []
        for kind in ("action", "panel", "report"):
            group = [c for c in cards if c.kind == kind][: REPORTS_LISTED if kind == "report" else None]
            out += [_line(c, tasks.get(c.task_id)) for c in group]
        gone = await panel_trash.recent(db)
        if gone:
            out += ["最近移除的面板（30 天内可 revive 找回）："]
            out += [f"- id={c.id} [已移除面板]「{c.title}」 · 移除于 {_local(c.removed_at)}" for c in gone]
        return ToolResult("\n".join(out) if out else "Home 上还什么都没有。")

    if action == "revive" and (refused := task_brief.fire_refusal(ctx.task_id, action)):
        return ToolResult(refused)
    if action == "revive":
        if not id:
            return ToolResult("revive 要给 id：先用 action=list 看“最近移除的面板”。")
        try:
            card, task = await panel_trash.revive(db, id)
        except LookupError as e:
            return ToolResult(f"{e}。先用 action=list 看“最近移除的面板”。")
        return ToolResult(f"面板「{card.title}」已放回 Home · cron {task.cron}，正在重新取数据（半分钟左右）。")

    card = await db.get(HomeCard, id) if id else None
    if card is None or card.dismissed:
        return ToolResult("没找到这张卡，先用 action=list 查 id。")
    task = await db.get(ScheduledTask, card.task_id) if card.task_id else None
    refused = task_brief.fire_refusal(ctx.task_id, action, card.task_id, removes_task=action == "dismiss" and card.kind == "panel")
    if refused:
        return ToolResult(refused)

    if action == "dismiss":
        if card.kind == "panel":
            await panel_trash.remove(db, card)
            return ToolResult(f"已从 Home 拿掉面板「{card.title}」，它不再刷新；30 天内可以用 revive 找回。")
        card.dismissed = True
        card.unread = False
        card.snoozed_until = None
        await db.commit()
        return ToolResult(f"已从 Home 拿掉「{card.title}」。")
    if action == "snooze":
        try:
            at = schedule.parse_local(until or "")
        except ValueError:
            return ToolResult("snooze 要给 until，格式 YYYY-MM-DD HH:MM（用户时区）。")
        try:
            card_snooze.snooze(card, at)
        except ValueError as e:
            return ToolResult(str(e))
        await db.commit()
        where = "收件箱" if card.kind == "report" else " Home "
        return ToolResult(f"「{card.title}」先收起来了，{until} 再放回{where}提醒。")
    if action == "unsnooze":
        if card.snoozed_until is None:
            return ToolResult(f"「{card.title}」本来就在 Home 上。")
        card.snoozed_until = None
        await db.commit()
        return ToolResult(f"「{card.title}」已放回 Home。")

    if card.kind != "panel" or task is None:
        return ToolResult(f"「{card.title}」不是面板，只能 dismiss。")
    if action == "read":
        return ToolResult(_read(card, task))
    if action == "runs":
        rows = await task_runs.history(db, task.id, RUNS_LISTED)
        from .tasks import _run  # 运行行的写法和 schedule_task runs 同一处
        return ToolResult("\n".join(_run(r) for r in rows) if rows else f"面板「{card.title}」还没刷新过。")
    if action == "refresh":
        if task.run_requested:
            return ToolResult(f"面板「{card.title}」已经在刷新了，稍后用 read 看结果。")
        asked = datetime.now(timezone.utc) - timedelta(seconds=1)
        task.run_requested = True
        await db.commit()
        return ToolResult(await _wait_refresh(task.id, card.id, asked))
    if action == "update":
        changes = {k: v for k, v in {"name": title, "prompt": prompt, "cron": cron}.items() if v}
        if not changes:
            return ToolResult("update 至少给 title、prompt、cron 之一。")
        if "cron" in changes:
            changes["run_at"] = None  # 面板只按 cron 重复刷新
        try:
            await task_store.update(db, task, changes)
        except ValueError as e:
            return ToolResult(str(e))
        return ToolResult(f"已更新面板「{task.name}」· cron {task.cron}。")
    return ToolResult(f"未知 action：{action}")


def _local(t: datetime | None) -> str:
    if t is None:
        return "—"
    return card_snooze._aware(t).astimezone(ZoneInfo(settings.timezone)).strftime("%m-%d %H:%M")


def _state(task: ScheduledTask) -> str:
    """刷新状态一行：诊断“面板不对 / 没更新”的依据（库里的戳，不靠对话记忆）。"""
    if task.paused_reason == task_runs.PAUSED_BY_FAILURES:
        plan = f"连续失败 {task.fail_streak} 次已自动暂停（修好后 update 或用户在任务页重新启用）"
    elif not task.active:
        plan = "用户暂停了，不会自动刷新"
    else:
        plan = f"cron {task.cron} · 下次 {_local(schedule.next_run_at(task))}"
    last = "从没刷新过" if task.last_run_at is None else (
        f"上次刷新 {_local(task.last_run_at)} " + ("成功" if task.last_status == "ok" else f"失败（连续 {task.fail_streak} 次）"))
    out = f"{plan} · {last}" + (" · 正在刷新" if task.run_requested else "")
    if task.wall:
        who = "要用户处理" if task_wall.fixable(task.wall) else "会自己再试"
        out += f" · 碰壁（{who}）：{task_wall.error_text(task.wall, task.wall_reason)}"
    return out


def _read(card: HomeCard, task: ScheduledTask) -> str:
    body = blocks_to_text(card.blocks or []).strip() or "（还没有内容）"
    if len(body) > READ_MAX:
        body = body[:READ_MAX] + f"…（还有 {len(body) - READ_MAX} 字）"
    memo = "、".join(w for w, v in (("做法", task.runbook), ("观察", task.note)) if v) or "还没有"
    return (f"面板「{card.title}」（id={card.id}，任务 id={task.id}）\n刷新状态：{_state(task)}\n"
            f"内容更新于 {_local(card.updated_at)}；记下的{memo}\n刷新指令：{task.prompt}\n\n当前内容：\n{body}")


async def _wait_refresh(task_id: str, card_id: str, asked: datetime) -> str:
    """等 worker 领走并跑完这次刷新（自己的会话轮询，不占这一轮的事务）；最多 REFRESH_WAIT 秒。"""
    loop = asyncio.get_running_loop()
    end = loop.time() + REFRESH_WAIT
    while True:
        async with SessionLocal() as db:
            task = await db.get(ScheduledTask, task_id)
            if task is None:
                return "面板在刷新时被删除了。"
            run = None if task.run_requested else await db.scalar(
                select(TaskRun).where(TaskRun.task_id == task_id, TaskRun.started_at >= asked)
                .order_by(TaskRun.started_at.desc()).limit(1))
            if run is not None and run.status != "running":
                card = await db.get(HomeCard, card_id)
                if run.status == "ok":
                    text = blocks_to_text(card.blocks or []).strip() if card else ""
                    return f"面板「{task.name}」刷新好了，{_local(run.finished_at)} 更新：\n{text[:600] or '（没有内容）'}"
                head = "碰壁" if run.wall else "失败"
                return f"面板「{task.name}」这次刷新{head}：{run.error}。上面还是上一次的内容。\n状态：{_state(task)}"
        if loop.time() >= end:
            return f"已经开始刷新，一分钟内还没跑完（模型或网站慢），稍后用 read 看结果。"
        await asyncio.sleep(REFRESH_POLL)
