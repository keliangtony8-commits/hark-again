"""网页版截图回归（设计 v2）：用假接口把 dist/ 渲染成几张图，和 docs/design-refs/ 对着看。

用法（见 frontend/README 或 assistant/README「截图」）：
  python3 -m venv /tmp/pw && /tmp/pw/bin/pip install playwright && /tmp/pw/bin/playwright install --with-deps chromium
  npm run build && /tmp/pw/bin/python scripts/shots.py [输出目录，默认 /tmp/shots/web]

所有 /api 请求由下面的 FIXTURES 应答，WebSocket 被接住但不回消息（连接显示为在线）。
时间固定在 Asia/Shanghai 白天，免得问候语和日期分隔随跑的时刻变。
"""
import atexit
import json
import os
import sys
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from playwright.sync_api import sync_playwright

DIST = Path(__file__).resolve().parent.parent / "dist"
OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/shots/web")
NOW = "2026-10-11T10:30:00+08:00"

TEXT = lambda t: {"type": "text", "text": t}


def _job(i, title, cmd, state="running", elapsed=96, tail=""):
    """后台任务快照（frontend/src/lib/types.ts 的 JobInfo）。"""
    return {"id": i, "title": title, "command": cmd, "state": state, "followup": "none", "elapsed": elapsed,
            "tail": tail, "started_at": "2026-10-11T10:20:00+08:00", "finished_at": None, "exit_code": None}


# 电脑（沙盒）状态：项目首屏和“我的电脑”页共用（ComputerStatus）。运行中、一个后台任务、一个常驻预览服务。
COMPUTER = {
    "workspace": "pr1", "name": "考研数学",
    "sandbox": {"state": "running", "memory_used": 268435456, "memory_limit": 1073741824,
                "started_at": "2026-10-11T09:40:00+08:00", "last_used_at": NOW, "idle_minutes": 3,
                "cpu_percent": 12.5, "oom_kills": 0, "outdated": False,
                "processes": [{"pid": 4211, "cpu": 8.5, "memory": 96468992, "elapsed": 420,
                               "command": "python -m http.server 8000"}]},
    "disk_used": 73400320, "disk_partial": False, "disk_limit": 536870912, "disk_level": "ok",
    "running_jobs": [_job("j3", "跑第三章习题", "python run_ch3.py", tail="正在算第 7 题…")],
    "services": [{**_job("s1", "预览服务", "python -m http.server 8000", elapsed=600), "health": "up", "ports": [8000], "uptime": 600}],
    "storage": {"files": 12582912, "installed": 31457280, "logs": 2097152, "spill": 0, "cache": 5242880, "cleanable": 7340032},
    "tools": [{"kind": "pip", "name": "sympy", "version": "1.13.3"}],
    "ports": [{"port": 8000, "loopback": False, "pid": 4211, "command": "python -m http.server 8000"}],
    "memory": {"used": 268435456, "limit": 1073741824, "other": 12582912, "rows": [
        {"kind": "process", "title": "python -m http.server 8000", "memory": 96468992, "processes": 1, "share": 0.36, "pid": 4211},
        {"kind": "job", "title": "跑第三章习题", "memory": 33554432, "processes": 1, "share": 0.12, "id": "j3"}]},
}
INBOX_IDLE = {"unread": 2, "latest": None}
BANNER_ITEM = {"id": "r9", "kind": "report", "title": "晚间复盘", "conversation_id": "c1", "task_id": "t3",
               "headline": "今天完成 4 件", "gist": "高数第三章刷完，错题 6 道已进错题本；明早 8 点图书馆抢座。",
               "created_at": NOW, "updated_at": NOW}
FIXTURES = {
    "/api/catalog/models": {"default": "fast", "models": [{"id": "fast", "label": "快速"}, {"id": "smart", "label": "深度"}]},
    "/api/inbox": {"unread": 2, "latest": None},  # 横幅截图时临时换成 BANNER_ITEM
    "/api/cards": [
        {"id": "a1", "kind": "action", "conversation_id": None, "task_id": None, "title": "本月花费已到预算的 82%",
         "blocks": [TEXT("按现在的速度，月底会超出约 ¥6。")], "action_prompt": None, "target": "usage",
         "dismissed": False, "unread": True, "updated_at": NOW},
        # v0.85/v0.89：助手提议的建议卡，一张待点、一张已交给助手
        {"id": "k3", "kind": "action", "origin": "agent", "action_label": "帮我订座", "conversation_id": None, "task_id": None,
         "title": "明早图书馆四楼靠窗还有空位", "blocks": [TEXT("8:00 开放预约，靠窗那排还剩 6 个。")],
         "action_prompt": "帮我约明早 8 点图书馆四楼靠窗的座位", "target": None,
         "image_url": "https://img.example.com/library-window.svg", "link_url": "https://www.seat.lib.example.edu/floor/4", "dismissed": False, "unread": True, "updated_at": NOW},
        {"id": "k4", "kind": "action", "origin": "agent", "action_label": "整理笔记", "conversation_id": "c1", "task_id": None,
         "title": "这周的高数笔记可以整理成提纲", "blocks": [TEXT("周五小测前过一遍，大约 10 分钟。")],
         "action_prompt": "把这周的高数笔记整理成一页提纲", "target": None, "dismissed": False, "unread": False, "updated_at": NOW},
        # v0.93：只有去处、没有指令的助手卡（眉题“需要你亲自处理”）
        {"id": "k5", "kind": "action", "origin": "agent", "action_label": None, "conversation_id": None, "task_id": None,
         "title": "GitHub 连接失效了", "blocks": [TEXT("令牌昨晚过期，代码仓库的定时同步停了。重新连一下就好。")],
         "action_prompt": None, "target": "connectors", "dismissed": False, "unread": True, "updated_at": NOW},
        {"id": "p1", "kind": "panel", "conversation_id": None, "task_id": "t1", "title": "今天的天气",
         "blocks": [{"type": "stats", "items": [{"label": "上海", "value": "24°C", "note": "多云"},
                                                {"label": "日落", "value": "17:32"}]}],
         "action_prompt": None, "target": None, "dismissed": False, "unread": False, "updated_at": NOW},
        {"id": "r1", "kind": "report", "conversation_id": "c1", "task_id": "t2", "title": "早间简报",
         "headline": "今天 · 10月11日 周日", "gist": "今天有两节课，下午 3 点交实验报告。",  # v1.08：一眼
         "blocks": [TEXT("**今天** 有两节课，下午 3 点交实验报告。")], "action_prompt": None, "target": None,
         "dismissed": False, "unread": True, "updated_at": NOW},
        {"id": "r2", "kind": "report", "conversation_id": "c1", "task_id": None, "title": "降噪耳机比价",
         "headline": "三款都在 ¥2000 内", "gist": "索尼 WH-1000XM5 京东今天降到 ¥1899，比上周低 ¥300。",
         "blocks": [TEXT("索尼 WH-1000XM5 京东今天降到 ¥1899。")], "action_prompt": None, "target": None,
         "dismissed": False, "unread": False, "updated_at": NOW},
    ],
    # 时钟固定 10:30（Asia/Shanghai，周日）：主页“今天”= 已完成 08:00 → 失败 09:00 → 下一个 11:30 → 已暂停 14:00 → 稍后 21:00（v1.02）；
    # 任务页同一批：自动暂停进“需要留意”、手动停的变淡、面板不进日程。
    "/api/tasks": [
        {"id": "t2", "name": "早间简报", "prompt": "", "cron": "0 8 * * *", "active": True, "output": "report",
         "run_requested": False, "last_run_at": "2026-10-11T00:00:20Z", "last_status": "ok", "next_run_at": None},
        {"id": "t5", "name": "背单词提醒", "prompt": "", "cron": "0 9 * * *", "active": True, "output": "report",
         "run_requested": False, "last_run_at": "2026-10-11T01:00:30Z", "last_status": "error", "next_run_at": None, "fail_streak": 1},
        {"id": "t6", "name": "图书馆抢座", "prompt": "", "cron": "30 11 * * *", "active": True, "output": "report",
         "run_requested": False, "last_run_at": None, "last_status": None, "next_run_at": None},
        {"id": "t4", "name": "周报整理", "prompt": "", "cron": "0 14 * * *", "active": False, "output": "report",
         "run_requested": False, "last_run_at": "2026-10-10T06:00:00Z", "last_status": "error", "next_run_at": None,
         "fail_streak": 3, "paused_reason": "failures"},
        {"id": "t3", "name": "晚间复盘", "prompt": "", "cron": "0 21 * * *", "active": True, "output": "report",
         "run_requested": False, "last_run_at": None, "last_status": None, "next_run_at": None},
        {"id": "t7", "name": "考研倒计时面板", "prompt": "", "cron": "0 7 * * *", "active": True, "output": "panel",
         "run_requested": False, "last_run_at": "2026-10-10T23:00:00Z", "last_status": "ok", "next_run_at": None},
        {"id": "t8", "name": "健身打卡", "prompt": "", "cron": "0 19 * * *", "active": False, "output": "report",
         "run_requested": False, "last_run_at": None, "last_status": None, "next_run_at": None},
    ],
    "/api/preferences": {"reply_language": "auto", "reply_languages": [
        {"code": "auto", "label": "跟随我的语言"}, {"code": "zh-Hans", "label": "简体中文"},
        {"code": "zh-Hant", "label": "繁體中文"}, {"code": "en", "label": "English"}]},
    "/api/projects": [
        {"id": "pr1", "name": "考研数学", "emoji": "📐", "rules": "每天一章，错题进错题本", "updated_at": NOW,
         "conversation_id": "c1", "last_active_at": NOW},
        {"id": "pr2", "name": "毕业设计", "emoji": "🎓", "rules": "", "updated_at": "2026-10-09T20:00:00+08:00",
         "conversation_id": "c9", "last_active_at": "2026-10-09T20:00:00+08:00"},
        {"id": "pr3", "name": "日本旅行", "emoji": "✈️", "rules": "预算 8000 以内\n优先公共交通", "updated_at": "2026-10-01T10:00:00+08:00",
         "conversation_count": 0, "last_active_at": None},
    ],
    "/api/conversations": [
        {"id": "c1", "title": "DeepSeek 和 GPT 的价格对比", "pinned": True, "updated_at": NOW},
        {"id": "c2", "title": "周末去杭州的安排", "pinned": False, "updated_at": "2026-10-10T18:00:00+08:00"},
        {"id": "c3", "title": "论文摘要润色", "pinned": False, "updated_at": "2026-10-08T09:00:00+08:00"},
        {"id": "c4", "title": "寄快递", "pinned": False, "updated_at": "2026-10-08T08:00:00+08:00"},
        {"id": "c5", "title": "帮我准备今天", "pinned": False, "updated_at": "2026-10-07T08:00:00+08:00"},
    ],
    # v0.87：助手缺信息时的信息表单（候选、选填、多行）
    "/api/conversations/c4": {"model": None, "messages": [
        {"id": "h1", "role": "user", "blocks": [TEXT("帮我把这箱书寄回家，下周三前到就行")], "created_at": NOW},
        {"id": "h2", "role": "assistant", "created_at": NOW, "blocks": [
            TEXT("寄件还差几样信息，填好我就去下单。"),
            {"type": "form", "id": "f2", "purpose": "info", "title": "寄件信息", "note": "填一次，我记进记忆，下次不用再问。",
             "fields": [{"name": "q1", "label": "收件人", "kind": "text", "value": "柯妈妈"},
                        {"name": "q2", "label": "电话", "kind": "phone"},
                        {"name": "q3", "label": "收件地址", "kind": "multiline"},
                        {"name": "q4", "label": "快递", "kind": "text", "options": ["顺丰", "京东", "中通"]},
                        {"name": "q5", "label": "备注", "kind": "text", "optional": True}],
             "remember": True, "action": "告诉助手", "state": "pending"}]},
    ]},
    # v1.03：“帮我准备今天”→ 当日简报卡（show_summary）+ 一句话；和 App shots_test c5 同一份
    "/api/conversations/c5": {"model": None, "messages": [
        {"id": "d1", "role": "user", "blocks": [TEXT("帮我准备今天")], "created_at": NOW},
        {"id": "d2", "role": "assistant", "created_at": NOW, "blocks": [
            {"type": "summary", "title": "今天 · 10月11日 周日", "subtitle": "3 件排定的事 · 1 张卡等你 · 2 条未读",
             "markdown": "## 时间线\n- **08:00** 早间简报 — 已完成\n- **09:00** 背单词提醒 — 失败了，等你看一眼\n- **11:30** 图书馆抢座 — 待运行\n\n"
                         "## 要留意\n- 周三前寄回那箱书（快递信息还差地址）\n- 图书馆四楼靠窗位今天 14:00 开放预约\n\n## 天气\n晴，18–25°C，下午有风。"},
            TEXT("上午最要紧的是把背单词那条修好，我已经在主页放了张卡，点一下我就去查。")]},
    ]},
    "/api/conversations/c1": {"model": None, "messages": [
        {"id": "m1", "role": "user", "blocks": [TEXT("帮我比较一下 DeepSeek 和 GPT 的 API 价格")], "created_at": "2026-10-10T21:00:00+08:00"},
        {"id": "m2", "role": "assistant", "created_at": "2026-10-10T21:00:05+08:00", "blocks": [
            TEXT("按每百万 token 算，**DeepSeek** 便宜一个数量级，日常对话足够用；需要更强推理时再切到深度模型。"),
            {"type": "table", "columns": ["模型", "输入", "输出"], "rows": [["DeepSeek-V3", "¥2", "¥8"], ["GPT-4o", "¥18", "¥72"]]}]},
        {"id": "m3", "role": "user", "blocks": [TEXT("那每个月 30 块预算够吗？")], "created_at": "2026-10-11T10:20:00+08:00"},
        {"id": "m4", "role": "assistant", "created_at": "2026-10-11T10:20:04+08:00", "blocks": [
            TEXT("够。按你现在每天约 40 次对话算，DeepSeek 一个月大约 ¥12，留出的余量还能跑每天的简报和面板刷新。")]},
        # v0.84：卡片块单独成卡（不套回复卡），正文段仍是回复卡
        {"id": "m5", "role": "user", "blocks": [TEXT("顺便帮我买那副 QCY 耳机")], "created_at": "2026-10-11T10:25:00+08:00"},
        {"id": "m6", "role": "assistant", "created_at": "2026-10-11T10:25:00+08:00", "blocks": [
            TEXT("券后 ¥229，送到学校南门驿站。确认后我去付款。"),
            {"type": "order", "id": "o1", "merchant": "QCY 京东自营旗舰店",
             "items": [{"name": "QCY HT08 主动降噪耳机", "price": "¥239.00", "qty": 1, "note": "黑色"}],
             "breakdown": [{"label": "运费", "amount": "¥0.00"}, {"label": "店铺券", "amount": "-¥10.00"}],
             "total": "¥229.00", "payment": "招商银行 储蓄卡 8841", "destination": "学校南门菜鸟驿站",
             "action": "确认下单", "state": "pending"}]},
    ]},
    # v3.0 设置搜索定位截图：安全页（两步验证 + 登录设备）
    "/api/auth/2fa": {"enabled": False, "recovery_left": 0},
    "/api/auth/sessions": {"sessions": [
        {"id": "s1", "label": "Chrome · Windows", "kind": "browser", "created_at": "2026-10-09T20:00:00+08:00", "last_seen_at": "2026-10-11T10:30:00+08:00", "current": True},
        {"id": "s2", "label": "Toyuis App · Android", "kind": "app", "created_at": "2026-10-08T09:00:00+08:00", "last_seen_at": "2026-10-11T08:10:00+08:00", "current": False}]},
    "/api/projects/pr1/files": [
        {"path": "真题/2024 数一.pdf", "name": "2024 数一.pdf", "size": 3145728, "mime": "application/pdf", "modified": 1791680400},
        {"path": "错题本.md", "name": "错题本.md", "size": 9000, "mime": "text/markdown", "modified": 1791600000},
        {"path": "笔记/第三章 中值定理.docx", "name": "第三章 中值定理.docx", "size": 240000, "mime": "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "modified": 1791500000},
        {"path": "背景.png", "name": "背景.png", "size": 820000, "mime": "image/png", "modified": 1790900000},
    ],
    # 项目首屏“电脑”一节：缺了这份 useComputer 读 running_jobs.length 会让整页白屏（v2.91 补上）
    "/api/projects/pr1/computer": {"workspace": "pr1", "name": "考研数学", "sandbox": {"state": "stopped"}, "disk_used": 52428800,
                                   "disk_partial": False, "running_jobs": [], "services": []},
    "/api/projects/pr1": {"id": "pr1", "name": "考研数学", "emoji": "📐", "rules": "每天一章，错题进错题本", "updated_at": NOW, "conversation_id": "c1"},
    # 项目首屏的“电脑”一节（v1.25）。形状照 frontend/src/lib/computer.ts 的 ComputerStatus；
    # 缺了它页面会白屏（读 s.sandbox.state 时炸），所以这张图以前一直拍不出来。
    "/api/projects/pr1/computer": COMPUTER,
    "/api/conversations/c1/usage": {"currency": "CNY", "priced": ["fast"], "total": {"calls": 4, "tokens": 5200, "cost": 0.012, "models": []}},
    "/api/usage": {"currency": "CNY", "budget": 30, "priced": ["fast"],
                   "today": {"calls": 18, "tokens": 42000, "cost": 0.41, "models": []},
                   "month": {"calls": 520, "tokens": 1250000, "cost": 24.6, "models": [
                       {"model": "smart", "calls": 120, "prompt_tokens": 520000, "completion_tokens": 130000, "cost": 17.2},
                       {"model": "fast", "calls": 400, "prompt_tokens": 480000, "completion_tokens": 120000, "cost": 7.4}]},
                   # v1.02：和 App 截图同一套“有数据的一个月”——每日图、最花钱的对话、上月同期（之前只有总数，下半页空着没法对照）
                   "daily": [{"date": f"2026-10-{d:02d}", "cost": c, "tokens": int(c * 50000), "calls": int(c * 21)}
                             for d, c in zip(range(1, 11), [1.8, 2.8, 1.2, 3.6, 2.2, 0.6, 0.4, 3.2, 2.4, 4.2])]
                            + [{"date": "2026-10-11", "cost": 0.41, "tokens": 42000, "calls": 18}],  # 今天 = today 合计
                   "conversations": [{"id": "c1", "title": "DeepSeek 和 GPT 的价格对比", "calls": 58, "tokens": 420000, "cost": 6.1},
                                     {"id": "c2", "title": "周末去杭州的安排", "calls": 31, "tokens": 260000, "cost": 3.8},
                                     {"id": "c9", "title": None, "calls": 12, "tokens": 90000, "cost": 1.2}],
                   "last_month": {"calls": 610, "tokens": 1500000, "cost": 28.0, "to_date": {"calls": 240, "tokens": 700000, "cost": 11.0}}},
    # 子页面（v0.52：桌面子页/弹层也要和一级页面同一套玻璃框架）
    "/api/profile": {"username": "keliang", "display_name": None, "assistant_name": None, "assistant_default": "Toyuis", "avatar": None, "greet": False},
    "/api/memories": [
        {"id": "mm1", "category": "偏好", "content": "回答用中文，先给结论再给理由", "updated_at": NOW},
        {"id": "mm2", "category": "偏好", "content": "预算有限，优先推荐便宜的方案", "updated_at": NOW},
        {"id": "mm3", "category": "事实", "content": "在读研究生，方向是计算机视觉", "updated_at": NOW},
    ],
    "/api/memory-digest": {"text": "你是一名预算有限的研究生，正在自己搭个人 AI 助手；喜欢先看结论，常问价格对比。", "generated_at": NOW, "count": 3, "memories": 3, "stale": False},
    "/api/tasks/t2/runs": [
        {"id": "r1", "trigger": "schedule", "status": "ok", "error": None, "conversation_id": "c1", "started_at": NOW, "finished_at": NOW, "duration_ms": 8200},
        {"id": "r2", "trigger": "manual", "status": "error", "error": "搜索服务超时", "conversation_id": None,
         "started_at": "2026-10-10T08:00:00+08:00", "finished_at": "2026-10-10T08:01:00+08:00", "duration_ms": 60000},
    ],
    "/api/catalog/skills": [
        {"id": "s1", "name": "网页调研", "description": "多来源搜索后汇总", "body": "", "builtin": True, "enabled": True},
        {"id": "s2", "name": "论文润色", "description": "学术英文润色，保留术语", "body": "", "builtin": False, "enabled": True},
        {"id": "s3", "name": "订餐", "description": "外卖下单", "body": "", "builtin": True, "enabled": False},
    ],
    "/api/connectors": [
        {"id": "google", "name": "Google", "desc": "日历、邮件、云盘", "logo": "", "status": "connected", "account": "me@example.com", "setup": None},
        {"id": "github", "name": "GitHub", "desc": "仓库与议题", "logo": "", "status": "unconfigured", "account": None,
         "setup": {"console": "https://github.com/settings/developers", "callback": "https://ai.example.com/api/oauth/callback",
                   "env": ["GITHUB_CLIENT_ID", "GITHUB_CLIENT_SECRET"]}},
    ],
    "/api/vault": [
        {"id": "v1", "kind": "api_key", "name": "DeepSeek", "username": None, "hosts": ["api.deepseek.com"], "header_name": "Authorization",
         "header_prefix": "Bearer ", "preview": "a3f9", "created_at": NOW},
    ],
    # v3.2.1：补上这几份（缺了「连接的账号」MCP 区和「记忆 → 笔记」两屏是空的）；形状 = lib/types.ts McpServerInfo / MemoryNote
    "/api/version": {"version": "3.2.1", "min_client": "0.0.0"},  # 关于页 / “我的 → 关于”行尾
    "/api/connectors/mcp": [
        {"id": "mcp1", "name": "Notion", "url": "https://mcp.notion.com/sse", "has_token": True, "problem": None},
    ],
    "/api/memory-notes": [
        {"id": "n1", "path": "people/mom.md", "title": "妈妈", "kind": "contact", "body": "生日 3 月 12 日；喜欢兰花，不吃辣。", "created_at": NOW, "updated_at": NOW},
        {"id": "n2", "path": "kaoyan.md", "title": "考研计划", "kind": "project", "body": "数学一，每天一章，错题进错题本。", "created_at": NOW, "updated_at": NOW},
    ],
    "/api/pages": [
        {"id": "pg1", "slug": "trip", "title": "日本旅行计划", "url": "https://example.com/p/trip", "updated": 1791680000, "published": True},
        {"id": "pg2", "slug": "cv", "title": "个人简历", "url": "https://example.com/p/cv", "updated": 1791500000, "published": False},
    ],
}



def _check_times(v, where="FIXTURES"):
    """假数据里的时间必须是带时区的 ISO（和真服务器 wire_time 一致）；写成别的格式浏览器会猜，日期分隔就错。"""
    from datetime import datetime
    if isinstance(v, dict):
        for k, x in v.items():
            if isinstance(x, str) and (k.endswith("_at") or k == "created_at"):
                assert datetime.fromisoformat(x).tzinfo, f"{where}.{k} 没带时区：{x}"
            _check_times(x, f"{where}.{k}")
    elif isinstance(v, list):
        for i, x in enumerate(v):
            _check_times(x, f"{where}[{i}]")


_check_times(FIXTURES)
_check_times(BANNER_ITEM, "BANNER_ITEM")


class _QuietHandler(SimpleHTTPRequestHandler):
    """静态请求别往 stderr 打访问日志：会把“跑完了”也刷成一片红，看不出到底成没成。"""

    def log_message(self, *a, **k) -> None:
        pass


def serve() -> str:
    handler = partial(_QuietHandler, directory=str(DIST))
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{srv.server_port}"


# 建议卡配图：外网图片在截图里拿不到，这里画一张同款“图书馆窗户”矢量图应答（和 App shots_test 的 _seedImage 一致）。
OFFER_IMAGE = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="400">'
    '<defs><linearGradient id="w" x2="0" y2="1"><stop offset="0" stop-color="#F3E3C8"/><stop offset="1" stop-color="#C9A27A"/></linearGradient>'
    '<linearGradient id="g" x2="0" y2="1"><stop offset="0" stop-color="#DDEBF2"/><stop offset="1" stop-color="#A9C7D8"/></linearGradient></defs>'
    '<rect width="800" height="400" fill="url(#w)"/>'
    + "".join(f'<rect x="{70 + i * 230}" y="50" width="200" height="230" fill="#6B4E37"/>'
              f'<rect x="{80 + i * 230}" y="60" width="180" height="210" fill="url(#g)"/>'
              f'<rect x="{167 + i * 230}" y="60" width="6" height="210" fill="#6B4E37"/>' for i in range(3))
    + '<rect y="300" width="800" height="26" fill="#8A6446"/></svg>'
)


def image(route):
    route.fulfill(status=200, content_type="image/svg+xml", body=OFFER_IMAGE)


# 页面请求了、但没有假数据的接口。这些会拿到 []，页面上少见一个字段就可能整屏白掉——
# 所以跑完把清单打出来（补 FIXTURES 时照这个清单补，别靠猜）；跑挂了也要打（atexit）。
MISSING: list[str] = []


def _report_missing() -> None:
    if not MISSING:
        return
    print("这页请求了但没有假数据（照这个清单补 FIXTURES）：")
    for m in sorted(set(MISSING)):
        print("  -", m)


atexit.register(_report_missing)

# v2.91 §N：项目里的对话列表带 status（服务器只在 ?project_id= 时发；主聊天列表不带）
PROJECT_STATUS = {"c1": "waiting", "c2": "running", "c3": "done", "c4": "waiting", "c5": "done"}


def api(route):
    path = route.request.url.split("://", 1)[1].split("/", 1)[1]
    if path.startswith("api/conversations?") and "project_id=" in path and "q=" not in path:
        body = [{**c, "status": PROJECT_STATUS.get(c["id"])} for c in FIXTURES["/api/conversations"]]
        return route.fulfill(status=200, content_type="application/json", body=json.dumps(body))
    path = "/" + path.split("?", 1)[0]
    if path.startswith("/api/conversations/") and path.endswith("/usage"):
        path = "/api/conversations/c1/usage"  # 每个对话的用量都用同一份（缺了标题栏用量会读空）
    if path.startswith("/api/usage/days/"):  # 每日图默认选中今天 → 那天的明细（缺了 total 页面会白屏）
        body = {"currency": "CNY", "priced": ["fast"], "date": path.rsplit("/", 1)[1],
                "total": {"calls": 18, "tokens": 42000, "cost": 0.41, "models": [
                    {"model": "fast", "calls": 18, "prompt_tokens": 34000, "completion_tokens": 8000, "cost": 0.41}]},
                "conversations": [{"id": "c1", "title": "DeepSeek 和 GPT 的价格对比", "calls": 9, "tokens": 21000, "cost": 0.22}]}
        return route.fulfill(status=200, content_type="application/json", body=json.dumps(body))
    if path.endswith("/save-to-project"):  # v1.16：存回复的回执（和服务器 reply_files.save 同形）
        body = {"project_id": "pr1", "project_name": "考研数学", "path": "API 价格对比.md", "name": "API 价格对比.md",
                "size": 1840, "mime": "text/markdown"}
        return route.fulfill(status=200, content_type="application/json", body=json.dumps(body))
    body = FIXTURES.get(path, [] if route.request.method == "GET" else {})
    if path not in FIXTURES:
        MISSING.append(f"{route.request.method} {path}")
    route.fulfill(status=200, content_type="application/json", body=json.dumps(body))


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    base = serve()
    with sync_playwright() as p:
        # 默认用 playwright 自带的 chromium；本机装不上（或只想用系统浏览器）时设 SHOTS_CHANNEL=chrome / msedge
        browser = p.chromium.launch(channel=os.environ.get("SHOTS_CHANNEL") or None)
        for theme in ("light", "dark"):
            for name, size in (("desktop", (1280, 820)), ("phone", (400, 860))):
                ctx = browser.new_context(viewport={"width": size[0], "height": size[1]}, device_scale_factor=2 if name == "phone" else 1,
                                          timezone_id="Asia/Shanghai", locale="zh-CN", color_scheme=theme)
                ctx.add_init_script(f"localStorage.setItem('assistant.token','shot');localStorage.setItem('assistant.server','{base}');")
                page = ctx.new_page()
                page.on("pageerror", lambda e: print("PAGE ERROR:", e))  # 页面崩了（白屏）时把原因打出来
                page.clock.set_fixed_time(NOW)
                page.route("**/api/**", api)
                page.route("https://img.example.com/**", image)
                page.route_web_socket("**/ws**", lambda ws: None)
                shots = [("home", "/#/"), ("projects", "/#/projects"), ("me", "/#/me"), ("me-preferences", "/#/me/preferences"), ("usage", "/#/me/usage"), ("project-chat", "/#/projects/pr1")]
                for shot, url in shots:
                    page.goto(base + url)
                    page.wait_for_timeout(700)
                    page.screenshot(path=str(OUT / f"{name}-{theme}-{shot}.png"))
                    if shot == "home":  # 主页滚到底：看建议卡下半截和右栏收尾（v0.94）
                        page.evaluate("document.querySelector('.page').scrollTo(0, 1e6)")
                        page.wait_for_timeout(400)
                        page.screenshot(path=str(OUT / f"{name}-{theme}-home-end.png"))
                        # v1.06：“今天”段（现在线 + 帮我准备今天 + 每天早上自动准备）
                        page.evaluate("document.querySelector('.today-now')?.scrollIntoView({block: 'center'})")
                        page.wait_for_timeout(400)
                        page.screenshot(path=str(OUT / f"{name}-{theme}-home-today.png"))
                        # v1.12：收件箱行（更多菜单 = 稍后再看 / 标为已读 / 收起）
                        page.evaluate("document.querySelector('.report-row')?.scrollIntoView({block: 'center'})")
                        page.wait_for_timeout(400)
                        page.screenshot(path=str(OUT / f"{name}-{theme}-home-inbox.png"))
                        page.get_by_label("稍后再看或收起").first.click()
                        page.wait_for_timeout(400)
                        page.screenshot(path=str(OUT / f"{name}-{theme}-inbox-menu.png"))
                        page.keyboard.press("Escape")
                        # v1.12：新报告横幅——换掉收件箱摘要，再触发一次“页面可见”让它立刻去问
                        FIXTURES["/api/inbox"] = {"unread": 3, "latest": BANNER_ITEM}
                        page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
                        page.wait_for_timeout(700)
                        page.screenshot(path=str(OUT / f"{name}-{theme}-banner.png"))
                        FIXTURES["/api/inbox"] = INBOX_IDLE
                # v1.16：项目里的对话——回复下“存到项目文件”→ 已存进一行；输入框“项目里的文件”选择弹层 → 待发名片
                page.goto(base + "/#/projects/pr1")
                page.wait_for_timeout(600)
                # v2.95 项目 = 一段对话：进项目直接就是那段聊天（c1），不再点对话列表
                page.wait_for_timeout(400)
                # v2.90.2：“存到项目文件”已经收进回复的 ⋯ 菜单（点菜单项“存成文件”）。
                # 挑那条有 markdown 的回复（假数据里的 m2）；最后一条 assistant 往往是订单卡，没有这一项。
                # ⋯ 平时 opacity:0（hover 才显形，触屏设备常显），所以先 hover 再点，否则第一次点会落空。
                more = page.locator('.msg.assistant[data-msg-id="m2"]').get_by_label("这条回复的操作")
                more.hover()
                more.click()
                page.get_by_role("menuitem", name="存成文件").click()
                page.wait_for_timeout(500)
                page.screenshot(path=str(OUT / f"{name}-{theme}-project-saved.png"))
                page.get_by_label("添加附件").first.click()
                page.wait_for_timeout(300)
                # 菜单项叫的是“项目文件”（lib/workspace.ts 的 workspaceFilesTitle），不是“项目里的文件”
                page.get_by_role("menuitem", name="项目文件", exact=True).click()
                page.wait_for_timeout(600)
                page.screenshot(path=str(OUT / f"{name}-{theme}-project-picker.png"))
                boxes = page.get_by_role("checkbox")
                boxes.nth(0).click()
                boxes.nth(1).click()
                page.wait_for_timeout(300)
                page.get_by_text("引用 2 个文件").click()
                page.wait_for_timeout(600)
                page.screenshot(path=str(OUT / f"{name}-{theme}-project-refs.png"))
                page.goto(base + "/#/chat")
                page.wait_for_timeout(500)
                if name == "desktop":
                    page.get_by_text("DeepSeek 和 GPT 的价格对比").first.click()
                else:
                    page.get_by_role("button", name="历史", exact=True).click()
                    page.wait_for_timeout(400)
                    page.screenshot(path=str(OUT / f"{name}-{theme}-drawer.png"))
                    page.get_by_text("DeepSeek 和 GPT 的价格对比").first.click()
                page.wait_for_timeout(800)
                page.screenshot(path=str(OUT / f"{name}-{theme}-chat.png"))
                # v1.16：主聊天里存回复 → 先选项目（v2.90.2 起同样收在回复的 ⋯ 菜单里）
                more = page.locator('.msg.assistant[data-msg-id="m2"]').get_by_label("这条回复的操作")
                more.hover()
                more.click()
                page.get_by_role("menuitem", name="存成文件").click()
                page.wait_for_timeout(600)
                page.screenshot(path=str(OUT / f"{name}-{theme}-save-picker.png"))
                page.keyboard.press("Escape")
                page.wait_for_timeout(300)
                if name == "phone":
                    page.get_by_role("button", name="历史", exact=True).click()
                    page.wait_for_timeout(400)
                page.get_by_text("寄快递").first.click()
                page.wait_for_timeout(800)
                page.screenshot(path=str(OUT / f"{name}-{theme}-chat-ask.png"))
                if name == "phone":
                    page.get_by_role("button", name="历史", exact=True).click()
                    page.wait_for_timeout(400)
                page.get_by_text("帮我准备今天").first.click()  # v1.06：简报卡（衬线标题、标题分层）
                page.wait_for_timeout(800)
                page.screenshot(path=str(OUT / f"{name}-{theme}-chat-day.png"))
                subs = [("memory", "/#/me/memory"), ("tasks", "/#/me/tasks"), ("task", "/#/me/tasks/t2"), ("skills", "/#/me/skills"),
                        ("connectors", "/#/me/connectors"), ("pages", "/#/me/pages")]  # v2.96 保险箱并进连接的账号
                for shot, url in subs:
                    page.goto(base + url)
                    page.wait_for_timeout(600)
                    page.screenshot(path=str(OUT / f"{name}-{theme}-sub-{shot}.png"))
                # v2.90.2 连接器“服务器还差一步”→ 配置引导弹层
                page.goto(base + "/#/me/connectors")
                page.wait_for_timeout(500)
                page.get_by_text("服务器还差一步").first.click()
                page.wait_for_timeout(600)
                page.screenshot(path=str(OUT / f"{name}-{theme}-sheet-oauth-setup.png"))
                # 弹层：主页“创建一个新面板”、项目“新建项目”
                page.goto(base + "/#/")
                page.wait_for_timeout(500)
                page.get_by_text("创建一个新面板").first.click()
                page.wait_for_timeout(500)
                page.screenshot(path=str(OUT / f"{name}-{theme}-sheet-panel.png"))
                page.goto(base + "/#/me/tasks")
                page.wait_for_timeout(500)
                page.get_by_label("新定时任务").first.click()
                page.wait_for_timeout(500)
                page.screenshot(path=str(OUT / f"{name}-{theme}-sheet-task.png"))
                # 确认框（ui/dialog.tsx）：连接的账号里一把密钥点“删除”
                page.goto(base + "/#/me/connectors")
                page.wait_for_timeout(500)
                page.get_by_label("的操作").first.click()  # v0.79：删除收进行尾菜单
                page.wait_for_timeout(300)
                page.get_by_role("menuitem", name="删除").first.click()
                page.wait_for_timeout(500)
                page.screenshot(path=str(OUT / f"{name}-{theme}-dialog.png"))
                page.keyboard.press("Escape")
                # v3.0 “我的”页底部设置搜索：有结果 / 无结果 / 点结果定位并闪一下
                page.goto(base + "/#/me")
                page.wait_for_timeout(500)
                page.get_by_placeholder("搜索设置").fill("深色")
                page.wait_for_timeout(500)
                page.screenshot(path=str(OUT / f"{name}-{theme}-me-search.png"))
                page.get_by_placeholder("搜索设置").fill("飞机票")
                page.wait_for_timeout(500)
                page.screenshot(path=str(OUT / f"{name}-{theme}-me-search-empty.png"))
                page.goto(base + "/#/me/security?focus=sessions")
                page.wait_for_timeout(450)
                page.screenshot(path=str(OUT / f"{name}-{theme}-me-focus.png"))
                if theme == "light":
                    page.goto(base + "/#/")
                    page.wait_for_timeout(500)
                    # 占位符带品牌名（Composer 里是 `给 ${appName} 发消息`，brand.ts 的 appName）
                    page.get_by_placeholder("给 Toyuis 发消息").click()
                    page.wait_for_timeout(500)
                    page.screenshot(path=str(OUT / f"{name}-{theme}-home-focused.png"))
                    page.goto(base + "/#/me/preferences")  # v2.81 起头像颜色在“偏好设置”里，不在“我的”首屏
                    page.wait_for_timeout(500)
                    page.get_by_label("换头像颜色").click()
                    page.wait_for_timeout(400)
                    page.screenshot(path=str(OUT / f"{name}-{theme}-avatar.png"))
                ctx.close()
                # 登录页（没有令牌）
                ctx = browser.new_context(viewport={"width": size[0], "height": size[1]}, device_scale_factor=2 if name == "phone" else 1,
                                          timezone_id="Asia/Shanghai", locale="zh-CN", color_scheme=theme)
                page = ctx.new_page()
                page.goto(base + "/")
                page.wait_for_timeout(500)
                page.screenshot(path=str(OUT / f"{name}-{theme}-login.png"))
                ctx.close()
        browser.close()
    print("wrote", OUT)


def section_n():
    """v2.91 §N 项目页：首屏状态胶囊、手机 ≡→+ 抽屉、进场药丸 / 停 1.5 秒收起 / 上翻浮出。只跑这一段：shots.py <目录> n"""
    OUT.mkdir(parents=True, exist_ok=True)
    base = serve()
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for theme in ("light", "dark"):
            for name, size in (("phone", (400, 860)), ("desktop", (1280, 820))):
                ctx = browser.new_context(viewport={"width": size[0], "height": size[1]}, device_scale_factor=2 if name == "phone" else 1,
                                          timezone_id="Asia/Shanghai", locale="zh-CN", color_scheme=theme)
                ctx.add_init_script(f"localStorage.setItem('assistant.token','shot');localStorage.setItem('assistant.server','{base}');")
                page = ctx.new_page()
                page.on("pageerror", lambda e: print("PAGE ERROR:", e))
                page.clock.set_fixed_time(NOW)
                page.route("**/api/**", api)
                page.route_web_socket("**/ws**", lambda ws: None)
                page.goto(base + "/#/projects/pr1")
                page.wait_for_timeout(800)
                page.screenshot(path=str(OUT / f"{name}-{theme}-n-project-home.png"))
                if name == "phone":  # v2.95：左上 ≡ = 项目切换栏（宽屏常驻左侧），开着时同一颗钮是“新建项目”
                    page.get_by_role("button", name="切换项目").click()
                    page.wait_for_timeout(500)
                    page.screenshot(path=str(OUT / f"{name}-{theme}-n-drawer.png"))
                ctx.close()
        browser.close()
    print("wrote", OUT)


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[2] == "n":
        section_n()
    else:
        main()
