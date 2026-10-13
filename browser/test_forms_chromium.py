"""真 Chromium 端到端（需要 playwright + chromium；没有就跳过）：python3 browser/test_forms_chromium.py
快照里下拉框有标签名 + 当前值 + 选项、勾选框有 checked；/act select 真把值改了（change 事件触发）；
不是 <select> 报“先点开”；对不上列出可选项；/act press Escape 关掉弹层、按在输入框上的 ArrowDown 被页面收到。"""
import asyncio, os, sys, tempfile
sys.path.insert(0, os.path.dirname(__file__))
try:
    import playwright  # noqa: F401
except ImportError:
    print("跳过：没装 playwright"); sys.exit(0)
os.environ.update(BROWSER_TOKEN="t", BROWSER_ALLOW_HOSTS="127.0.0.1")
from fastapi import HTTPException  # noqa: E402
import service  # noqa: E402

service.STATE = tempfile.mkdtemp()
service.DOWNLOADS = tempfile.mkdtemp()

PAGE = """<title>预约</title>
<label for=city>城市</label><select id=city onchange="document.getElementById('out').textContent='选了'+this.value">
<option value="" disabled selected>请选择</option><option value=bj>北京</option><option value=sh>上海</option>
<option value=pd>上海浦东</option></select>
<label><input type=checkbox id=agree> 同意条款</label>
<input id=q placeholder=搜索 onkeydown="if(event.key==='ArrowDown')document.getElementById('out').textContent='候选1'">
<div id=modal>弹层<script>addEventListener('keydown',e=>{if(e.key==='Escape')document.getElementById('modal').remove()})</script></div>
<button disabled>已售罄</button>
<p id=out>无</p>"""


async def serve(r, w):
    await r.readuntil(b"\r\n\r\n")
    body = ("<meta charset=utf-8>" + PAGE).encode()
    w.write(b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nConnection: close\r\nContent-Length: %d\r\n\r\n" % len(body) + body)
    await w.drain(); w.close()


def el(snap, tag, typ=None):
    return next(e for e in snap["elements"] if e["tag"] == tag and (typ is None or e["type"] == typ))


async def act(**kw):
    return await service.act("f", service.ActIn(**kw))


async def bad(**kw):
    try:
        await act(**kw)
    except HTTPException as e:
        assert e.status_code == 400
        return e.detail
    raise AssertionError(kw)


async def main():
    srv = await asyncio.start_server(serve, "127.0.0.1", 0)
    base = f"http://127.0.0.1:{srv.sockets[0].getsockname()[1]}"
    s = await service.goto("f", service.GotoIn(url=base + "/"))
    sel = el(s, "select")
    assert sel["name"] == "城市" and sel["value"] == "请选择", sel
    assert sel["options"] == ["北京", "上海", "上海浦东"] and sel["count"] == 3, sel
    box = el(s, "input", "checkbox")
    assert box["name"] == "同意条款" and box["checked"] is False, box
    assert el(s, "button").get("disabled") is True

    s = await act(action="select", ref=sel["ref"], text="上海")
    assert el(s, "select")["value"] == "上海" and "选了sh" in s["text"], s["text"]
    s = await act(action="select", ref=el(s, "select")["ref"], text="浦东")
    assert el(s, "select")["value"] == "上海浦东"
    d = await bad(action="select", ref=el(s, "select")["ref"], text="杭州")
    assert "没有「杭州」" in d and "「北京」" in d, d
    d = await bad(action="select", ref=el(s, "input", "checkbox")["ref"], text="x")
    assert "browser_click" in d, d

    s = await act(action="click", ref=el(s, "input", "checkbox")["ref"])
    assert el(s, "input", "checkbox")["checked"] is True

    q = next(e for e in s["elements"] if e["name"] == "搜索")
    s = await act(action="press", ref=q["ref"], text="↓")
    assert "候选1" in s["text"], s["text"]
    assert "弹层" in s["text"]
    s = await act(action="press", text="esc")
    assert "弹层" not in s["text"], s["text"]
    s = await act(action="press", text="Space")
    d = await bad(action="press", text="Control+w")
    assert "只支持" in d, d
    srv.close()
    print("test_forms_chromium ok")


asyncio.run(main())
