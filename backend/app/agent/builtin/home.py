"""Home：把“要反复看的信息”做成定时刷新的面板（create_panel），以及在对话里管理 Home 上已有的东西（manage_home）：
“我主页上有什么”“把天气面板改成每天 7 点”“删掉那个比分面板”“收件箱那条不用管了”。
面板本质是 output=panel 的定时任务，增删改都走 app/task_store.py（与接口、客户端同一套规则：改名卡片跟着改、删除连卡带记录）。"""
from sqlalchemy import select

from zoneinfo import ZoneInfo

from ... import card_snooze, card_targets, home_offers, schedule, task_store, web_guard
from ...config import settings
from ...models import HomeCard, ScheduledTask
from ..tools import ToolContext, ToolResult, tool
from .display import IMAGE_PROBE_TIMEOUT, probe_image

_KIND = {"action": "建议", "panel": "面板", "report": "收件箱"}
REPORTS_LISTED = 10  # 收件箱只列最近几条，免得把上下文撑大


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
       "required": ["title"]})
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
      "refresh 让面板立即刷新；update 改面板的 title/prompt/cron（cron 同 create_panel）；"
      "dismiss 拿掉一张卡：建议/收件箱只是隐藏，面板会连同它的定时刷新一起删除（不可恢复，用户没明确要删就先问）；"
      "snooze 把建议/收件箱先收起，到 until 再放回来并提醒（“明早再提醒我”）；unsnooze 现在就放回来。"
      "id 先用 list 拿到。",
      {"type": "object", "properties": {
          "action": {"type": "string", "enum": ["list", "refresh", "update", "dismiss", "snooze", "unsnooze"]},
          "id": {"type": "string", "description": "卡片 id"},
          "title": {"type": "string"},
          "prompt": {"type": "string"},
          "cron": {"type": "string"},
          "until": {"type": "string", "description": "snooze 用：用户时区的 YYYY-MM-DD HH:MM，最多 30 天内"}},
       "required": ["action"]})
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
        return ToolResult("\n".join(out) if out else "Home 上还什么都没有。")

    card = await db.get(HomeCard, id) if id else None
    if card is None or card.dismissed:
        return ToolResult("没找到这张卡，先用 action=list 查 id。")
    task = await db.get(ScheduledTask, card.task_id) if card.task_id else None

    if action == "dismiss":
        if card.kind == "panel" and task is not None:
            await task_store.remove(db, task)  # 连卡带运行记录
            return ToolResult(f"已删除面板「{card.title}」，它不会再刷新。")
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
    if action == "refresh":
        task.run_requested = True
        await db.commit()
        return ToolResult(f"面板「{card.title}」开始刷新，半分钟内更新。")
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
