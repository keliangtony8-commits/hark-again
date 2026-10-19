"""真 Cloudflare Turnstile（官方测试 sitekey，要联网；没装 playwright / 连不上 challenges.cloudflare.com 就跳过）：
python3 browser/test_turnstile_chromium.py

sitekey 3x00000000000000000000FF = Cloudflare 官方“强制出交互复选框、点了总是通过”的测试钥匙
（https://developers.cloudflare.com/turnstile/troubleshooting/testing/）。它不做机器人判定，所以这里验证的是
“接管的点击能不能真的送进 Turnstile 的封闭 shadow root + 跨源 iframe 并被它接受”，不是“能不能骗过风控”。
点击走接管同一条路：live.parse → service._input（按页面坐标注入鼠标），不用选择器 / element.click。

沙盒没有直连外网、只有 HTTPS_PROXY 时：会话的出网代理换成那个上游代理（只在本测试里）；VPS 上直连。"""
import asyncio, json, os, sys, tempfile, urllib.parse, urllib.request
sys.path.insert(0, os.path.dirname(__file__))
try:
    import playwright  # noqa: F401
except ImportError:
    print("跳过：没装 playwright"); sys.exit(0)
try:
    urllib.request.urlopen("https://challenges.cloudflare.com/turnstile/v0/api.js", timeout=10)
except Exception as e:  # noqa: BLE001
    print(f"跳过：连不上 challenges.cloudflare.com（{type(e).__name__}）"); sys.exit(0)
os.environ.update(BROWSER_TOKEN="t", BROWSER_ALLOW_HOSTS="127.0.0.1")
import live  # noqa: E402
import service  # noqa: E402

service.STATE = tempfile.mkdtemp()
service.DOWNLOADS = tempfile.mkdtemp()
_up = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
if _up:
    u = urllib.parse.urlsplit(_up)
    service._egress.proxy_for = lambda name: {"server": f"http://{u.hostname}:{u.port}", "bypass": "127.0.0.1",
                                              "username": urllib.parse.unquote(u.username or ""), "password": urllib.parse.unquote(u.password or "")}

W, H = service.VIEW["width"], service.VIEW["height"]
SITEKEY = "3x00000000000000000000FF"
PAGE = """<!doctype html><meta charset=utf-8><title>turnstile</title><body style="margin:0">
<script src="https://challenges.cloudflare.com/turnstile/v0/api.js" async defer></script>
<div style="position:absolute;left:200px;top:150px"><div class="cf-turnstile" data-sitekey="%s" data-callback="ok"></div></div>
<script>window.__tok = null; function ok(t) { window.__tok = t }</script>""" % SITEKEY


async def serve(r, w):
    await r.readuntil(b"\r\n\r\n")
    body = PAGE.encode()
    w.write(b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nConnection: close\r\nContent-Length: %d\r\n\r\n" % len(body) + body)
    await w.drain(); w.close()


async def main():
    srv = await asyncio.start_server(serve, "127.0.0.1", 0)
    await service.goto("t", service.GotoIn(url=f"http://127.0.0.1:{srv.sockets[0].getsockname()[1]}/"))
    page = await service._session("t")
    box = None
    for _ in range(60):  # 等 widget 的 iframe 出来、排好版（300×65）
        await asyncio.sleep(0.5)
        fr = next((f for f in page.frames if "challenges.cloudflare.com" in f.url), None)
        if fr:
            box = await (await fr.frame_element()).bounding_box()
            if box and box["width"] > 100:
                break
    assert box, "Turnstile 没渲染出来"
    await asyncio.sleep(2)  # 复选框出现
    assert await page.evaluate("window.__tok") is None
    # 复选框在 widget 左侧约 30px、垂直居中：按页面坐标点（选择器够不着封闭 shadow root 里的跨源 iframe）
    x, y = box["x"] + 30, box["y"] + box["height"] / 2
    await service._input("t", live.parse(json.dumps({"t": "mouse", "x": x / W, "y": y / H, "hold": 90})))
    tok = None
    for _ in range(40):
        await asyncio.sleep(0.5)
        tok = await page.evaluate("window.__tok")
        if tok:
            break
    assert tok == "XXXX.DUMMY.TOKEN.XXXX", tok  # 测试钥匙通过时固定发这个假令牌
    srv.close()
    print("test_turnstile_chromium ok")


asyncio.run(main())
