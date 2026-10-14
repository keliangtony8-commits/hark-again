"""真 Chromium 端到端（需要 playwright + chromium；没有就跳过）：python3 browser/test_shadow_chromium.py
网页组件（Web Components）的 open 影子树：里面的按钮 / 下拉 / 输入框进快照、编号连续唯一；
按 ref 点击、选择、填写、代填登录都生效（定位器穿透影子树）；嵌套组件也走；组件文字带【组件】标题，
插槽里的字不重复；隐藏组件、closed 影子树不收；内嵌框里的组件照样收；DEPTH_MAX 限住嵌套层数。"""
import asyncio, os, sys, tempfile
sys.path.insert(0, os.path.dirname(__file__))
try:
    import playwright  # noqa: F401
except ImportError:
    print("跳过：没装 playwright"); sys.exit(0)
os.environ.update(BROWSER_TOKEN="t", BROWSER_ALLOW_HOSTS="127.0.0.1")
import shadow  # noqa: E402
import service  # noqa: E402

service.STATE = tempfile.mkdtemp()
service.DOWNLOADS = tempfile.mkdtemp()

DEFS = """<script>
const def = (tag, html, mode = 'open') => customElements.define(tag, class extends HTMLElement {
  constructor() { super(); this.attachShadow({mode}).innerHTML = html; } });
def('qty-stepper', '<span id=q>数量 1</span><button aria-label="加一件" onclick="this.getRootNode().getElementById(\\'q\\').textContent=\\'数量 2\\'">+</button>');
def('buy-box', `<div><b>羊毛围巾 ¥89</b><select aria-label="颜色"><option>灰色</option><option>驼色</option></select>
  <qty-stepper></qty-stepper><p id=s>未加入</p>
  <button onclick="const r=this.getRootNode();r.getElementById('s').textContent='已加入 '+r.querySelector('select').value">加入购物车</button><slot></slot></div>`);
def('cookie-consent', '<div>我们使用 Cookie<button onclick="this.getRootNode().host.remove()">同意</button></div>');
def('login-card', `<label>账号 <input id=u></label><label>密码 <input type=password id=p></label>
  <button onclick="this.getRootNode().getElementById('m').textContent='登录为 '+this.getRootNode().getElementById('u').value">登录</button><p id=m></p>`);
def('secret-box', '<button>关闭的组件按钮</button>', 'closed');
def('hidden-box', '<button>隐藏组件按钮</button><p>隐藏组件文字</p>');
</script>"""
PAGES = {
    "/": lambda: DEFS + """<title>店铺</title><h1>冬季上新</h1>
<buy-box><span>插槽里的说明</span></buy-box><cookie-consent></cookie-consent><login-card></login-card>
<secret-box></secret-box><hidden-box style="display:none"></hidden-box><iframe src="/frame" width=400 height=150></iframe>""",
    "/frame": lambda: DEFS + "<cookie-consent></cookie-consent>",
}


async def serve(r, w):
    head = (await r.readuntil(b"\r\n\r\n")).decode()
    path = head.split(" ")[1].split("?")[0]
    body = ("<meta charset=utf-8>" + PAGES.get(path, lambda: "404")()).encode()
    w.write(b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nConnection: close\r\nContent-Length: %d\r\n\r\n" % len(body) + body)
    await w.drain(); w.close()


def el(snap, name, frame=None):
    return next(e for e in snap["elements"] if e["name"] == name and e.get("frame") == frame)


def names(snap):
    return [e["name"] for e in snap["elements"]]


async def act(**kw):
    return await service.act("s", service.ActIn(**kw))


async def main():
    srv = await asyncio.start_server(serve, "127.0.0.1", 0)
    port = srv.sockets[0].getsockname()[1]
    await service.goto("s", service.GotoIn(url=f"http://127.0.0.1:{port}/"))
    await asyncio.sleep(0.5)
    s = await service.snapshot("s")
    refs = [e["ref"] for e in s["elements"]]
    assert len(refs) == len(set(refs)) and refs == [str(i + 1) for i in range(len(refs))], refs
    n = names(s)
    for want in ("颜色", "加一件", "加入购物车", "同意", "登录"):
        assert want in n, (want, n)
    assert n.index("颜色") < n.index("加一件") < n.index("加入购物车") < n.index("同意"), n  # 文档顺序，嵌套组件在中间
    assert "关闭的组件按钮" not in n and "隐藏组件按钮" not in n, n
    assert el(s, "同意", "同站")  # 内嵌框里的组件
    t = s["text"]
    assert "【组件 · buy-box】" in t and "羊毛围巾 ¥89" in t and "【组件 · qty-stepper】\n数量 1" in t, t
    assert t.count("插槽里的说明") == 1 and "隐藏组件文字" not in t, t
    assert t.index("【组件 · cookie-consent】") < t.index("【内嵌框 · 同站】"), t  # 组件是页面本身，排在框前
    assert el(s, "颜色")["value"] == "灰色" and el(s, "颜色")["options"] == ["灰色", "驼色"]

    s = await act(action="select", ref=el(s, "颜色")["ref"], text="驼色")
    s = await act(action="click", ref=el(s, "加一件")["ref"])
    assert "数量 2" in s["text"], s["text"]
    s = await act(action="click", ref=el(s, "加入购物车")["ref"])
    assert "已加入 驼色" in s["text"], s["text"]
    s = await service.login("s", service.LoginIn(user_ref=el(s, "账号")["ref"], pass_ref=el(s, "密码")["ref"],
                                                 username="小明", password="pw", submit=False))
    s = await act(action="click", ref=el(s, "登录")["ref"])
    assert "登录为 小明" in s["text"] and "pw" not in s["text"], s["text"]
    s = await act(action="click", ref=el(s, "同意")["ref"])
    assert "我们使用 Cookie" in s["text"] and s["text"].count("我们使用 Cookie") == 1, s["text"]  # 主页的横幅没了，框里的还在

    shadow.DEPTH_MAX = 1  # 只走一层：嵌套的 qty-stepper 不走
    s = await service.snapshot("s")
    assert "加一件" not in names(s) and "加入购物车" in names(s), names(s)
    await service.close("s", forget=True)
    srv.close()
    print("test_shadow_chromium ok")


asyncio.run(main())
