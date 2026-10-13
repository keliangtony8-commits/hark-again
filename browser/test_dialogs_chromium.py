"""真 Chromium 端到端（需要 playwright + chromium；没有就跳过）：python3 browser/test_dialogs_chromium.py
没说好的 confirm 被取消（页面看到 false）并记进快照 dialogs；带 dialog=accept 再点 → 页面看到 true；
alert 原话进快照；prompt 填模型给的字；同一张快照取走后不再重复；用户在实时画面里亲手点（/mouse）= 确定；
连环弹框超过 DIALOGS_MAX 个后 confirm 一律取消、只记条数，页面不会卡死。"""
import asyncio, os, sys, tempfile
sys.path.insert(0, os.path.dirname(__file__))
try:
    import playwright  # noqa: F401
except ImportError:
    print("跳过：没装 playwright"); sys.exit(0)
os.environ.update(BROWSER_TOKEN="t", BROWSER_ALLOW_HOSTS="127.0.0.1")
import dialogs  # noqa: E402
import service  # noqa: E402

service.STATE = tempfile.mkdtemp()
service.DOWNLOADS = tempfile.mkdtemp()

PAGE = """<title>地址</title>
<button id=rm style="position:fixed;left:0;top:0;width:200px;height:60px"
 onclick="document.getElementById('out').textContent = confirm('确定移除这个地址吗？') ? '已移除' : '没移除'">移除地址</button>
<div style="height:80px"></div><button onclick="alert('手机号格式不对')">提交</button>
<button onclick="document.getElementById('out').textContent = '备注=' + prompt('写个备注', '无')">备注</button>
<button onclick="for(let i=0;i<8;i++) confirm('第'+i+'次'); document.getElementById('out').textContent='连环完'">连环</button>
<p id=out>无</p>"""


async def serve(r, w):
    await r.readuntil(b"\r\n\r\n")
    body = ("<meta charset=utf-8>" + PAGE).encode()
    w.write(b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nConnection: close\r\nContent-Length: %d\r\n\r\n" % len(body) + body)
    await w.drain(); w.close()


def ref(snap, name):
    return next(e["ref"] for e in snap["elements"] if e["name"] == name)


async def act(**kw):
    return await service.act("d", service.ActIn(**kw))


async def main():
    srv = await asyncio.start_server(serve, "127.0.0.1", 0)
    base = f"http://127.0.0.1:{srv.sockets[0].getsockname()[1]}"
    s = await service.goto("d", service.GotoIn(url=base + "/"))
    assert "dialogs" not in s

    s = await act(action="click", ref=ref(s, "移除地址"))
    assert "没移除" in s["text"], s["text"]
    assert s["dialogs"] == [{"kind": "confirm", "message": "确定移除这个地址吗？", "accepted": False, "auto": True}], s.get("dialogs")
    s = await service.snapshot("d")
    assert "dialogs" not in s  # 取走一次就没了

    s = await act(action="click", ref=ref(s, "移除地址"), dialog="accept")
    assert "已移除" in s["text"] and s["dialogs"][0]["accepted"] is True and s["dialogs"][0]["auto"] is False, s

    s = await act(action="click", ref=ref(s, "提交"))
    assert s["dialogs"] == [{"kind": "alert", "message": "手机号格式不对", "accepted": True, "auto": True}], s.get("dialogs")

    s = await act(action="click", ref=ref(s, "备注"), dialog="accept", dialog_text="放门口")
    assert "备注=放门口" in s["text"] and s["dialogs"][0]["text"] == "放门口", s
    s = await act(action="click", ref=ref(s, "备注"))
    assert "备注=null" in s["text"], s["text"]

    # 用户亲手点（实时画面）：确认框 = 确定
    await service.mouse("d", service.PointIn(x=50 / 1280, y=30 / 800))
    await asyncio.sleep(0.5)
    s = await service.snapshot("d")
    assert "已移除" in s["text"] and s["dialogs"][0]["accepted"] is True, s

    s = await act(action="click", ref=ref(s, "连环"), dialog="accept")
    assert "连环完" in s["text"], s["text"]
    d = s["dialogs"]
    assert len(d) == dialogs.DIALOGS_MAX + 1 and d[-1] == {"kind": "more", "more": 8 - dialogs.DIALOGS_MAX}, d
    assert all(x["accepted"] for x in d[:dialogs.DIALOGS_MAX]), d
    srv.close()
    print("test_dialogs_chromium ok")


asyncio.run(main())
