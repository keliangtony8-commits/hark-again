"""真 Chromium 端到端（需要 playwright + chromium；没有就跳过）：python3 browser/test_frames_chromium.py
主页面 + 同站 iframe + 跨站 iframe（127.0.0.2 ≠ 127.0.0.1，另起渲染进程）+ 1×1 统计像素框：
看得见的框里的元素进快照、编号全局唯一、带 frame 标签；框里的文字带【内嵌框】标题；
按 ref 在跨站框里填卡号、点按钮、代填登录都生效；像素框不收；框数超过 FRAME_MAX 报 frames_more；
框里换页后旧编号报“页面已经换了”。"""
import asyncio, os, sys, tempfile
sys.path.insert(0, os.path.dirname(__file__))
try:
    import playwright  # noqa: F401
except ImportError:
    print("跳过：没装 playwright"); sys.exit(0)
os.environ.update(BROWSER_TOKEN="t", BROWSER_ALLOW_HOSTS="127.0.0.1,127.0.0.2")
import frames  # noqa: E402
import service  # noqa: E402
from fastapi import HTTPException  # noqa: E402

service.STATE = tempfile.mkdtemp()
service.DOWNLOADS = tempfile.mkdtemp()
PORT = 0

PAGES = {
    "/": lambda: f"""<title>结账</title><h1>订单 #881</h1><button>返回购物车</button>
<iframe src="/coupon" width=400 height=120></iframe>
<iframe src="http://127.0.0.2:{PORT}/pay" width=500 height=260></iframe>
<iframe src="http://127.0.0.2:{PORT}/pixel" width=1 height=1></iframe>""",
    "/coupon": lambda: """<p>优惠券</p><input placeholder="输入优惠码"><button onclick="document.querySelector('p').textContent='已用券 减5元'">使用</button>""",
    "/pay": lambda: """<p id=s>请填写卡号</p><input placeholder="卡号" id=c>
<button onclick="document.getElementById('s').textContent='已提交 ' + document.getElementById('c').value">支付</button>
<input placeholder="账号" id=u><input type=password placeholder="密码" id=p>
<button onclick="document.getElementById('s').textContent='登录为 ' + document.getElementById('u').value">登录</button>
<a href="/done">下一步</a>""",
    "/done": lambda: "<p>支付完成页</p><button>完成</button>",
    "/pixel": lambda: "<button>像素里的按钮</button>",
    "/many": lambda: "".join(f'<iframe src="/coupon?{i}" width=300 height=100></iframe>' for i in range(4)),
}


async def serve(r, w):
    head = (await r.readuntil(b"\r\n\r\n")).decode()
    path = head.split(" ")[1].split("?")[0]
    body = ("<meta charset=utf-8>" + PAGES.get(path, lambda: "404")()).encode()
    w.write(b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nConnection: close\r\nContent-Length: %d\r\n\r\n" % len(body) + body)
    await w.drain(); w.close()


def el(snap, name):
    return next(e for e in snap["elements"] if e["name"] == name)


async def act(**kw):
    return await service.act("f", service.ActIn(**kw))


async def main():
    global PORT
    srv = await asyncio.start_server(serve, "0.0.0.0", 0)
    PORT = srv.sockets[0].getsockname()[1]

    s = await service.goto("f", service.GotoIn(url=f"http://127.0.0.1:{PORT}/"))
    await asyncio.sleep(0.5)
    s = await service.snapshot("f")
    refs = [e["ref"] for e in s["elements"]]
    assert len(refs) == len(set(refs)), refs
    assert "frame" not in el(s, "返回购物车")
    assert el(s, "输入优惠码")["frame"] == "同站" and el(s, "卡号")["frame"] == "127.0.0.2", s["elements"]
    assert not any(e["name"] == "像素里的按钮" for e in s["elements"])  # 1×1 框不收
    assert "【内嵌框 · 127.0.0.2】\n请填写卡号" in s["text"] and "【内嵌框 · 同站】" in s["text"], s["text"]
    assert "frames_more" not in s

    s = await act(action="type", ref=el(s, "卡号")["ref"], text="4242 4242")
    s = await act(action="click", ref=el(s, "支付")["ref"])
    assert "已提交 4242 4242" in s["text"], s["text"]
    s = await act(action="click", ref=el(s, "使用")["ref"])
    assert "已用券 减5元" in s["text"]
    s = await act(action="click", ref=el(s, "返回购物车")["ref"])  # 主页面的编号照常

    s = await service.login("f", service.LoginIn(user_ref=el(s, "账号")["ref"], pass_ref=el(s, "密码")["ref"],
                                                 username="小明", password="pw", submit=False))
    s = await act(action="click", ref=el(s, "登录")["ref"])
    assert "登录为 小明" in s["text"] and "pw" not in s["text"]

    old = el(s, "支付")["ref"]
    s = await act(action="click", ref=el(s, "下一步")["ref"])
    assert "支付完成页" in s["text"] and el(s, "完成")["frame"] == "127.0.0.2"
    try:
        await act(action="click", ref=old)
        raise AssertionError("旧编号应该报错")
    except HTTPException as e:
        assert e.status_code == 400 and "页面已经换了" in e.detail, e.detail

    frames.FRAME_MAX = 2
    await service.goto("f", service.GotoIn(url=f"http://127.0.0.1:{PORT}/many"))
    await asyncio.sleep(0.5)
    s = await service.snapshot("f")
    assert s.get("frames_more") == 2 and s["text"].count("【内嵌框") == 2, (s.get("frames_more"), s["text"])
    await service.close("f", forget=True)
    srv.close()
    print("test_frames_chromium ok")


asyncio.run(main())
