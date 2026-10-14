"""真 Chromium 端到端（需要 playwright + chromium；没有就跳过）：python3 browser/test_region_chromium.py
直接调 service.py 的 goto：网页看到的 navigator.language / Accept-Language / Intl 时区 = goto 带的地区（region.py）；
同一会话改了语言 → 重开后网页看到新语言，登录 cookie 还在；坏值退回 zh-CN / Asia/Shanghai，不让会话起不来。"""
import asyncio, os, sys, tempfile
sys.path.insert(0, os.path.dirname(__file__))
try:
    import playwright  # noqa: F401
except ImportError:
    print("跳过：没装 playwright"); sys.exit(0)
os.environ.update(BROWSER_TOKEN="t", BROWSER_ALLOW_HOSTS="127.0.0.1")
import service  # noqa: E402

service.STATE = tempfile.mkdtemp()
service.DOWNLOADS = tempfile.mkdtemp()
seen: list[str] = []  # 每次请求的 Accept-Language

PAGE = ("<meta charset=utf-8><title>地区</title><p id=o></p><script>document.getElementById('o').textContent="
        "'LANG=' + navigator.language + ' TZ=' + Intl.DateTimeFormat().resolvedOptions().timeZone + ' C=' + document.cookie;"
        "document.cookie='sid=abc; max-age=3600'</script>")


async def serve(r, w):
    req = (await r.readuntil(b"\r\n\r\n")).decode()
    for line in req.split("\r\n"):
        if line.lower().startswith("accept-language:"):
            seen.append(line.split(":", 1)[1].strip())
    body = PAGE.encode()
    w.write(b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nConnection: close\r\nContent-Length: %d\r\n\r\n" % len(body) + body)
    await w.drain(); w.close()


async def main():
    srv = await asyncio.start_server(serve, "127.0.0.1", 0)
    url = f"http://127.0.0.1:{srv.sockets[0].getsockname()[1]}/"
    s = await service.goto("r", service.GotoIn(url=url, locale="en-US", timezone="America/New_York"))
    assert "LANG=en-US TZ=America/New_York C=" in s["text"], s["text"]
    assert seen[-1].startswith("en-US"), seen
    first = service._sessions["r"][0]
    # 同设置再开：复用（cookie 已在）
    s = await service.goto("r", service.GotoIn(url=url, locale="en-US", timezone="America/New_York"))
    assert service._sessions["r"][0] is first and "C=sid=abc" in s["text"], s["text"]
    # 用户改成繁体 + 东京：重开，cookie 跟着存档带过来
    s = await service.goto("r", service.GotoIn(url=url, locale="zh-TW", timezone="Asia/Tokyo"))
    assert service._sessions["r"][0] is not first, "应当重开"
    assert "LANG=zh-TW TZ=Asia/Tokyo C=sid=abc" in s["text"], s["text"]
    assert seen[-1].startswith("zh-TW"), seen
    # 坏值：退回默认，照样能开
    s = await service.goto("bad", service.GotoIn(url=url, locale="en US;x", timezone="Mars/Olympus"))
    assert "LANG=zh-CN TZ=Asia/Shanghai" in s["text"], s["text"]
    for n in list(service._sessions):
        await service.close(n, forget=True)
    srv.close()
    print("✓ test_region_chromium：语言 / 时区跟设置，改了重开保登录，坏值退默认")

asyncio.run(main())
