"""网页版截图回归（设计 v2）：用假接口把 dist/ 渲染成几张图，和 docs/design-refs/ 对着看。

用法（见 frontend/README 或 assistant/README「截图」）：
  python3 -m venv /tmp/pw && /tmp/pw/bin/pip install playwright && /tmp/pw/bin/playwright install --with-deps chromium
  npm run build && /tmp/pw/bin/python scripts/shots.py [输出目录，默认 /tmp/shots/web]

所有 /api 请求由下面的 FIXTURES 应答，WebSocket 被接住但不回消息（连接显示为在线）。
时间固定在 Asia/Shanghai 白天，免得问候语和日期分隔随跑的时刻变。
"""
import json
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
FIXTURES = {
    "/api/catalog/models": {"default": "fast", "models": [{"id": "fast", "label": "快速"}, {"id": "smart", "label": "深度"}]},
    "/api/inbox": {"unread": 2, "latest": None},
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
         "blocks": [TEXT("**今天** 有两节课，下午 3 点交实验报告。")], "action_prompt": None, "target": None,
         "dismissed": False, "unread": True, "updated_at": NOW},
    ],
    "/api/tasks": [
        {"id": "t2", "name": "早间简报", "prompt": "", "cron": "0 8 * * *", "active": True, "output": "report",
         "run_requested": False, "last_run_at": NOW, "last_status": "ok", "next_run_at": None},
        {"id": "t3", "name": "晚间复盘", "prompt": "", "cron": "0 21 * * *", "active": True, "output": "report",
         "run_requested": False, "last_run_at": None, "last_status": None, "next_run_at": None},
    ],
    "/api/projects": [
        {"id": "pr1", "name": "考研数学", "emoji": "📐", "rules": "每天一章，错题进错题本", "updated_at": NOW,
         "conversation_count": 12, "last_active_at": NOW},
        {"id": "pr2", "name": "毕业设计", "emoji": "🎓", "rules": "", "updated_at": "2026-10-09T20:00:00+08:00",
         "conversation_count": 3, "last_active_at": "2026-10-09T20:00:00+08:00"},
        {"id": "pr3", "name": "日本旅行", "emoji": "✈️", "rules": "预算 8000 以内\n优先公共交通", "updated_at": "2026-10-01T10:00:00+08:00",
         "conversation_count": 0, "last_active_at": None},
    ],
    "/api/conversations": [
        {"id": "c1", "title": "DeepSeek 和 GPT 的价格对比", "pinned": True, "updated_at": NOW},
        {"id": "c2", "title": "周末去杭州的安排", "pinned": False, "updated_at": "2026-10-10T18:00:00+08:00"},
        {"id": "c3", "title": "论文摘要润色", "pinned": False, "updated_at": "2026-10-08T09:00:00+08:00"},
        {"id": "c4", "title": "寄快递", "pinned": False, "updated_at": "Thu 2026-10-08 8:00 AM CST (UTC+08:00)"},
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
    "/api/conversations/c1": {"model": None, "messages": [
        {"id": "m1", "role": "user", "blocks": [TEXT("帮我比较一下 DeepSeek 和 GPT 的 API 价格")], "created_at": "2026-10-10T21:00:00+08:00"},
        {"id": "m2", "role": "assistant", "created_at": "2026-10-10T21:00:05+08:00", "blocks": [
            TEXT("按每百万 token 算，**DeepSeek** 便宜一个数量级，日常对话足够用；需要更强推理时再切到深度模型。"),
            {"type": "table", "columns": ["模型", "输入", "输出"], "rows": [["DeepSeek-V3", "¥2", "¥8"], ["GPT-4o", "¥18", "¥72"]]}]},
        {"id": "m3", "role": "user", "blocks": [TEXT("那每个月 30 块预算够吗？")], "created_at": "2026-10-11T10:20:00+08:00"},
        {"id": "m4", "role": "assistant", "created_at": "2026-10-11T10:20:04+08:00", "blocks": [
            TEXT("够。按你现在每天约 40 次对话算，DeepSeek 一个月大约 ¥12，留出的余量还能跑每天的简报和面板刷新。")]},
        # v0.84：卡片块单独成卡（不套回复卡），正文段仍是回复卡
        {"id": "m5", "role": "user", "blocks": [TEXT("顺便帮我买那副 QCY 耳机")], "created_at": "Sun 2026-10-11 10:25 AM CST (UTC+08:00)"},
        {"id": "m6", "role": "assistant", "created_at": "Sun 2026-10-11 10:25 AM CST (UTC+08:00)", "blocks": [
            TEXT("券后 ¥229，送到学校南门驿站。确认后我去付款。"),
            {"type": "order", "id": "o1", "merchant": "QCY 京东自营旗舰店",
             "items": [{"name": "QCY HT08 主动降噪耳机", "price": "¥239.00", "qty": 1, "note": "黑色"}],
             "breakdown": [{"label": "运费", "amount": "¥0.00"}, {"label": "店铺券", "amount": "-¥10.00"}],
             "total": "¥229.00", "payment": "招商银行 储蓄卡 8841", "destination": "学校南门菜鸟驿站",
             "action": "确认下单", "state": "pending"}]},
    ]},
    "/api/projects/pr1": {"id": "pr1", "name": "考研数学", "emoji": "📐", "rules": "每天一章，错题进错题本", "updated_at": NOW},
    "/api/conversations/c1/usage": {"currency": "CNY", "priced": ["fast"], "total": {"calls": 4, "tokens": 5200, "cost": 0.012, "models": []}},
    "/api/usage": {"currency": "CNY", "budget": 30, "priced": ["fast"],
                   "today": {"calls": 18, "tokens": 42000, "cost": 0.41, "models": []},
                   "month": {"calls": 520, "tokens": 1250000, "cost": 24.6, "models": []}},
    # 子页面（v0.52：桌面子页/弹层也要和一级页面同一套玻璃框架）
    "/api/auth/me": {"username": "keliang"},
    "/api/memories": [
        {"id": "mm1", "category": "偏好", "content": "回答用中文，先给结论再给理由", "updated_at": NOW},
        {"id": "mm2", "category": "偏好", "content": "预算有限，优先推荐便宜的方案", "updated_at": NOW},
        {"id": "mm3", "category": "事实", "content": "在读研究生，方向是计算机视觉", "updated_at": NOW},
    ],
    "/api/memory-digest": {"text": "你是一名预算有限的研究生，正在自己搭个人 AI 助手；喜欢先看结论，常问价格对比。", "generated_at": NOW, "count": 3, "memories": 3, "stale": False},
    "/api/tasks/t2/runs": [
        {"id": "r1", "trigger": "schedule", "status": "ok", "error": None, "conversation_id": "c1", "started_at": NOW, "finished_at": NOW, "duration_ms": 8200},
        {"id": "r2", "trigger": "manual", "status": "error", "error": "搜索服务超时", "conversation_id": None,
         "started_at": "Sat 2026-10-10 8:00 AM CST (UTC+08:00)", "finished_at": "Sat 2026-10-10 8:01 AM CST (UTC+08:00)", "duration_ms": 60000},
    ],
    "/api/catalog/skills": [
        {"id": "s1", "name": "网页调研", "description": "多来源搜索后汇总", "body": "", "builtin": True, "enabled": True},
        {"id": "s2", "name": "论文润色", "description": "学术英文润色，保留术语", "body": "", "builtin": False, "enabled": True},
        {"id": "s3", "name": "订餐", "description": "外卖下单", "body": "", "builtin": True, "enabled": False},
    ],
    "/api/connectors": [
        {"id": "google", "name": "Google", "desc": "日历、邮件、云盘", "logo": "", "configured": True, "account": "me@example.com"},
        {"id": "github", "name": "GitHub", "desc": "仓库与议题", "logo": "", "configured": False, "account": None},
    ],
    "/api/vault": [
        {"id": "v1", "kind": "api_key", "name": "DeepSeek", "username": None, "hosts": ["api.deepseek.com"], "header_name": "Authorization",
         "header_prefix": "Bearer ", "preview": "sk-…a3f9", "created_at": NOW},
    ],
    "/api/pages": [
        {"id": "pg1", "slug": "trip", "title": "日本旅行计划", "url": "https://example.com/p/trip", "updated": 1791680000, "published": True},
        {"id": "pg2", "slug": "cv", "title": "个人简历", "url": "https://example.com/p/cv", "updated": 1791500000, "published": False},
    ],
}


def serve() -> str:
    handler = partial(SimpleHTTPRequestHandler, directory=str(DIST))
    handler.log_message = lambda *a, **k: None
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


def api(route):
    path = route.request.url.split("://", 1)[1].split("/", 1)[1]
    path = "/" + path.split("?", 1)[0]
    if path.startswith("/api/conversations/") and path.endswith("/usage"):
        path = "/api/conversations/c1/usage"  # 每个对话的用量都用同一份（缺了标题栏用量会读空）
    body = FIXTURES.get(path, [] if route.request.method == "GET" else {})
    route.fulfill(status=200, content_type="application/json", body=json.dumps(body))


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    base = serve()
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for theme in ("light", "dark"):
            for name, size in (("desktop", (1280, 820)), ("phone", (400, 860))):
                ctx = browser.new_context(viewport={"width": size[0], "height": size[1]}, device_scale_factor=2 if name == "phone" else 1,
                                          timezone_id="Asia/Shanghai", locale="zh-CN", color_scheme=theme)
                ctx.add_init_script(f"localStorage.setItem('assistant.token','shot');localStorage.setItem('assistant.server','{base}');")
                page = ctx.new_page()
                page.clock.set_fixed_time(NOW)
                page.route("**/api/**", api)
                page.route("https://img.example.com/**", image)
                page.route_web_socket("**/ws**", lambda ws: None)
                shots = [("home", "/#/"), ("projects", "/#/projects"), ("me", "/#/me"), ("usage", "/#/me/usage"), ("project-chat", "/#/projects/pr1")]
                for shot, url in shots:
                    page.goto(base + url)
                    page.wait_for_timeout(700)
                    page.screenshot(path=str(OUT / f"{name}-{theme}-{shot}.png"))
                    if shot == "home":  # 主页滚到底：看建议卡下半截和右栏收尾（v0.94）
                        page.evaluate("document.querySelector('.page').scrollTo(0, 1e6)")
                        page.wait_for_timeout(400)
                        page.screenshot(path=str(OUT / f"{name}-{theme}-home-end.png"))
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
                if name == "phone":
                    page.get_by_role("button", name="历史", exact=True).click()
                    page.wait_for_timeout(400)
                page.get_by_text("寄快递").first.click()
                page.wait_for_timeout(800)
                page.screenshot(path=str(OUT / f"{name}-{theme}-chat-ask.png"))
                subs = [("memory", "/#/me/memory"), ("tasks", "/#/me/tasks"), ("task", "/#/me/tasks/t2"), ("skills", "/#/me/skills"),
                        ("connectors", "/#/me/connectors"), ("vault", "/#/me/vault"), ("pages", "/#/me/pages")]
                for shot, url in subs:
                    page.goto(base + url)
                    page.wait_for_timeout(600)
                    page.screenshot(path=str(OUT / f"{name}-{theme}-sub-{shot}.png"))
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
                # 确认框（ui/dialog.tsx）：钥匙页点“删除”
                page.goto(base + "/#/me/vault")
                page.wait_for_timeout(500)
                page.get_by_label("的操作").first.click()  # v0.79：删除收进行尾菜单
                page.wait_for_timeout(300)
                page.get_by_role("menuitem", name="删除").first.click()
                page.wait_for_timeout(500)
                page.screenshot(path=str(OUT / f"{name}-{theme}-dialog.png"))
                page.keyboard.press("Escape")
                if theme == "light":
                    page.goto(base + "/#/")
                    page.wait_for_timeout(500)
                    page.get_by_placeholder("给助手发消息").click()
                    page.wait_for_timeout(500)
                    page.screenshot(path=str(OUT / f"{name}-{theme}-home-focused.png"))
                    page.goto(base + "/#/me")
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


if __name__ == "__main__":
    main()
