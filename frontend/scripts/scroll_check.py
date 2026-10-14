"""聊天贴底跟随回归（v2.79，用户 10-14 16:02）：在真浏览器里验 useStickToBottom 的规则。

用法：npm run build && /tmp/pw/bin/python scripts/scroll_check.py
用 shots.py 的假接口打开一段对话，往最后一条回复里一段段追加文字（= 流式变高），检查：
  1. 在底部时跟到“真正的底”（含输入胶囊让位），最后一行不被胶囊挡住；
  2. 滚轮往上翻后再追加，不会被拽回底部，出现“回到最新”；
  3. 点“回到最新”回到底部并恢复跟随，按钮消失。
"""
import sys

from playwright.sync_api import sync_playwright

import shots

DIST_OK = shots.DIST.exists() or sys.exit("先 npm run build")

GROW = """(n) => { const m = [...document.querySelectorAll('.msg.assistant')].pop();
  for (let i = 0; i < n; i++) { const p = document.createElement('p'); p.className = 'grow'; p.textContent = '流式追加的一行 ' + i; m.appendChild(p); } }"""
DIST = "(() => { const t = document.querySelector('.thread'); return t.scrollHeight - t.scrollTop - t.clientHeight; })()"


def main():
    # 消息多到能滚：把 c1 复制几轮
    msgs = shots.FIXTURES["/api/conversations/c1"]["messages"]
    shots.FIXTURES["/api/conversations/c1"]["messages"] = [dict(m, id=f"{m['id']}-{k}") for k in range(4) for m in msgs]
    base = shots.serve()
    fails = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1280, "height": 820}, timezone_id="Asia/Shanghai", locale="zh-CN")
        ctx.add_init_script(f"localStorage.setItem('assistant.token','shot');localStorage.setItem('assistant.server','{base}');")
        page = ctx.new_page()
        page.on("pageerror", lambda e: fails.append(f"PAGE ERROR: {e}"))
        page.clock.set_fixed_time(shots.NOW)
        page.route("**/api/**", shots.api)
        page.route_web_socket("**/ws**", lambda ws: None)
        page.goto(base + "/#/chat")
        page.wait_for_timeout(500)
        page.get_by_text("DeepSeek 和 GPT 的价格对比").first.click()
        page.wait_for_timeout(900)

        def check(ok, what):
            print(("ok  " if ok else "FAIL") + " " + what)
            if not ok:
                fails.append(what)

        check(page.evaluate(DIST) <= 1, f"打开对话就在真正的底部（距底 {page.evaluate(DIST)}px）")
        for _ in range(5):
            page.evaluate(GROW, 3)
            page.wait_for_timeout(120)
        d = page.evaluate(DIST)
        check(d <= 1, f"流式变高时跟到真正的底（距底 {d}px）")
        last = page.locator("p.grow").last.bounding_box()
        foot = page.locator(".floating-footer").bounding_box()
        check(last["y"] + last["height"] <= foot["y"] + 1, "最后一行在输入胶囊上方，没被挡住")
        check(page.locator(".jump-latest").count() == 0, "跟随时没有“回到最新”")

        page.mouse.move(640, 300)
        page.mouse.wheel(0, -600)
        page.wait_for_timeout(400)
        top = page.evaluate("document.querySelector('.thread').scrollTop")
        for _ in range(5):
            page.evaluate(GROW, 3)
            page.wait_for_timeout(120)
        top2 = page.evaluate("document.querySelector('.thread').scrollTop")
        check(abs(top2 - top) <= 1, f"往上翻后不被拽回底部（scrollTop {top} → {top2}）")
        check(page.locator(".jump-latest").is_visible(), "往上翻后出现“回到最新”")
        page.screenshot(path=sys.argv[1] if len(sys.argv) > 1 else "/tmp/shots/web/desktop-light-jump-latest.png")

        page.locator(".jump-latest").click()
        page.wait_for_timeout(900)
        check(page.evaluate(DIST) <= 1, f"点“回到最新”回到底部（距底 {page.evaluate(DIST)}px）")
        page.evaluate(GROW, 4)
        page.wait_for_timeout(200)
        check(page.evaluate(DIST) <= 1, "回到底部后恢复跟随")
        check(page.locator(".jump-latest").count() == 0, "回到底部后按钮消失")
        browser.close()
    if fails:
        print("\n".join(fails))
        sys.exit(1)
    print("scroll_check ok")


if __name__ == "__main__":
    main()
