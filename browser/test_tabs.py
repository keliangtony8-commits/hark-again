"""标签页规则单元测试（不需要 Chromium）：python3 browser/test_tabs.py"""
import os, sys
sys.path.insert(0, os.path.dirname(__file__))
import tabs


class P:
    def __init__(self, url): self.url, self.closed = url, False
    def is_closed(self): return self.closed
    def __repr__(self): return self.url


a = P("https://shop.test/list")
t = tabs.Tabs(a)
# 没变化：还是 a，不出说明
mv = tabs.follow(t, [a], now=0)
assert mv.page is a and mv.kind == "" and t.take_note() is None
# 网站开了新标签页 → 切过去
b = P("https://shop.test/item/1")
t.on_page(b)
mv = tabs.follow(t, [a, b], now=1)
assert mv.page is b and mv.kind == "opened" and t.current is b
note = t.take_note()
assert note == {"kind": "opened", "url": "https://shop.test/item/1", "from": "https://shop.test/list", "tabs": 2}, note
assert t.take_note() is None  # 只说一次
# 新页被网站关了 → 退回 a
b.closed = True
mv = tabs.follow(t, [a, b], now=2)
assert mv.page is a and mv.kind == "closed" and t.take_note()["tabs"] == 1
# 当前页崩了 → 关掉、在原网址重开
t.on_crash(a)
mv = tabs.follow(t, [a], now=3)
assert mv.page is None and mv.kind == "crashed" and mv.reload == "https://shop.test/list" and mv.close == [a]
assert t.take_note() == {"kind": "crashed", "url": "https://shop.test/list"}
c = P("https://shop.test/list")
t.adopt(c)
t.on_page(c)  # service 自己开的页也会触发 page 事件：不能算网站开的新标签
mv = tabs.follow(t, [c], now=4)
assert mv.page is c and mv.kind == "", mv
# 同一网址 60 秒内又崩 → 不再重开（防循环），开空白页说明
t.on_crash(c)
mv = tabs.follow(t, [c], now=10)
assert mv.page is None and mv.kind == "crash_loop" and mv.reload == "" and t.take_note()["kind"] == "crash_loop"
# 过了窗口再崩 → 又可以重开一次
d = P("https://shop.test/list"); t.adopt(d); t.on_crash(d)
mv = tabs.follow(t, [d], now=10 + tabs.RELOAD_WINDOW_S + 1)
assert mv.kind == "crashed"
# 超过 TABS_MAX：关最早的，当前页（最新开的）留着
e = P("https://x.test/1"); t2 = tabs.Tabs(e)
others = [P(f"https://x.test/{i}") for i in range(2, 6)]
for p in others:
    t2.on_page(p)
mv = tabs.follow(t2, [e] + others, now=0)
assert mv.page is others[-1] and mv.kind == "opened"
assert mv.close == [e, others[0]], mv.close  # 5 页 → 留 3 页
assert t2.take_note()["tabs"] == tabs.TABS_MAX
# 网站开的页刚开就崩了：不切过去
f = P("https://y.test/"); t3 = tabs.Tabs(f); g = P("https://y.test/pop")
t3.on_page(g); t3.on_crash(g)
mv = tabs.follow(t3, [f, g], now=0)
assert mv.page is f and mv.kind == ""
# 所有页都没了 → 开空白页（closed，没有网址）
f.closed = True
mv = tabs.follow(t3, [f, g], now=1)
assert mv.page is None and mv.kind == "closed" and mv.reload == ""
print("✓ 标签页规则测试通过")
