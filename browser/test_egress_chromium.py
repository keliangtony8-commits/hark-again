"""真 Chromium 端到端（需要装了 playwright + chromium；没有就跳过）：python3 browser/test_egress_chromium.py
允许名单里的“NAS”页面里藏了：<img> 指向 127.0.0.1、fetch 到解析为 10.0.0.5 的域名、链接 302 跳到 127.0.0.1。
期望：页面本身打开；三处内网请求都被出网关卡拦下并记到会话上；内网服务器一次都没被碰到（localhost 也走代理）。"""
import asyncio, sys, os
sys.path.insert(0, os.path.dirname(__file__))
import egress
try:
    from playwright.async_api import async_playwright
except ImportError:
    print("跳过：没装 playwright"); sys.exit(0)
hits = []
async def main():
    async def secret(r, w):
        hits.append(await r.read(1000)); w.write(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nno"); await w.drain(); w.close()
    s2 = await asyncio.start_server(secret, "127.0.0.1", 0); p2 = s2.sockets[0].getsockname()[1]
    page_html = f"<html><title>NAS</title><img src='http://127.0.0.1:{p2}/img'><script>fetch('http://evil.example/x').catch(()=>0)</script><a href='/go'>go</a></html>"
    async def origin(r, w):
        req = await r.readuntil(b"\r\n\r\n")
        if b"GET /go" in req:
            w.write(f"HTTP/1.1 302 Found\r\nLocation: http://127.0.0.1:{p2}/redir\r\nContent-Length: 0\r\n\r\n".encode())
        else:
            b = page_html.encode(); w.write(b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nContent-Length: %d\r\n\r\n" % len(b) + b)
        await w.drain(); w.close()
    s1 = await asyncio.start_server(origin, "127.0.0.1", 0); p1 = s1.sockets[0].getsockname()[1]
    async def res(h, port):
        return {"nas.home": ["127.0.0.1"], "evil.example": ["10.0.0.5"]}.get(h) or (_ for _ in ()).throw(OSError("nx"))
    g = egress.Egress("nas.home", resolve=res); await g.start()
    pw = await async_playwright().start()
    b = await pw.chromium.launch(proxy={"server": "http://per-context"}, args=["--disable-dev-shm-usage","--force-webrtc-ip-handling-policy=disable_non_proxied_udp"])
    ctx = await b.new_context(proxy=g.proxy_for("s1"), service_workers="block")
    page = await ctx.new_page()
    await page.goto(f"http://nas.home:{p1}/", wait_until="load"); await page.wait_for_timeout(800)
    assert await page.title() == "NAS"
    hosts = sorted(b["host"] for b in g.take_blocked("s1"))
    assert hosts == ["127.0.0.1", "evil.example"], hosts
    try:
        await page.goto(f"http://nas.home:{p1}/go", timeout=10000)
    except Exception:
        pass  # Chromium 版本不同：要么显示代理的 403 页，要么报错——都行，关键是下面两条
    assert [b["host"] for b in g.take_blocked("s1")] == ["127.0.0.1"]
    assert hits == [], hits
    print("✓ 真 Chromium：页面里的图片、fetch、302 重定向进内网都被拦，内网服务器没被碰到")
    await b.close(); await pw.stop()
asyncio.run(main())
