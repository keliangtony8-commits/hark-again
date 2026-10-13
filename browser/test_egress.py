"""出网关卡冒烟测试（不需要 Chromium，用真 socket）：python3 browser/test_egress.py
- 没带代理账号 → 407；口令错 → 407
- CONNECT 内网 IP / localhost / 解析到内网的域名（含“一公一私”的 rebinding 样子）→ 403，记到对的会话、同主机去重、取走即清
- 允许名单里的主机放行：CONNECT 隧道双向通；明文 http 改写成相对路径、去掉 Proxy-Authorization、只转一个请求
- 连的是查过的那个 IP（假解析返回 127.0.0.1 → 真的连到本机测试服务器，不再二次解析）
"""
import asyncio
import base64
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
import egress  # noqa: E402

DNS = {"evil.example": ["8.8.8.8", "10.0.0.5"], "nas.home": ["127.0.0.1"], "public.example": ["93.184.216.34"]}


async def fake_resolve(host, port):
    if host not in DNS:
        raise OSError("nx")
    return DNS[host]


def auth(user, pw):
    return "Proxy-Authorization: Basic " + base64.b64encode(f"{user}:{pw}".encode()).decode() + "\r\n"


async def ask(port, raw: bytes) -> bytes:
    r, w = await asyncio.open_connection("127.0.0.1", port)
    w.write(raw)
    await w.drain()
    out = await asyncio.wait_for(r.read(65536), 5)
    w.close()
    return out


async def main():
    seen = []

    async def origin(r, w):  # 本机测试服务器：明文 http 回显请求行；隧道里回显收到的字节
        data = await r.read(4096)
        seen.append(data)
        if data.startswith(b"GET "):
            w.write(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok")
        else:
            w.write(b"echo:" + data)
        await w.drain()
        w.close()

    srv = await asyncio.start_server(origin, "127.0.0.1", 0)
    oport = srv.sockets[0].getsockname()[1]
    g = egress.Egress("nas.home", resolve=fake_resolve)
    port = await g.start()
    assert g.proxy_for("a") == {"server": f"http://127.0.0.1:{port}", "username": "a", "password": g.secret}

    out = await ask(port, b"CONNECT example.com:443 HTTP/1.1\r\nHost: example.com\r\n\r\n")
    assert out.startswith(b"HTTP/1.1 407") and b"Proxy-Authenticate: Basic" in out, out
    out = await ask(port, f"CONNECT example.com:443 HTTP/1.1\r\n{auth('a', 'wrong')}\r\n".encode())
    assert out.startswith(b"HTTP/1.1 407"), out
    print("✓ 没口令 / 口令错 → 407")

    A = auth("a", g.secret)
    for target in ("10.0.0.1:443", "127.0.0.1:80", "localhost:443", "[::ffff:192.168.1.1]:443", "evil.example:443",
                   "sandbox.internal:9000", "169.254.169.254:80"):
        out = await ask(port, f"CONNECT {target} HTTP/1.1\r\n{A}\r\n".encode())
        assert out.startswith(b"HTTP/1.1 403"), (target, out)
    out = await ask(port, f"GET http://10.0.0.1/x HTTP/1.1\r\nHost: 10.0.0.1\r\n{A}\r\n".encode())
    assert out.startswith(b"HTTP/1.1 403"), out
    out = await ask(port, f"CONNECT nowhere.example:443 HTTP/1.1\r\n{A}\r\n".encode())
    assert out.startswith(b"HTTP/1.1 403"), out
    blocked = g.take_blocked("a")
    hosts = [b["host"] for b in blocked]
    assert hosts == ["10.0.0.1", "127.0.0.1", "localhost", "::ffff:192.168.1.1", "evil.example", "sandbox.internal",
                     "169.254.169.254", "nowhere.example"], hosts  # 10.0.0.1 两次只留一条
    assert "10.0.0.5" in blocked[4]["reason"], blocked[4]
    assert g.take_blocked("a") == [] and g.take_blocked("b") == []
    print("✓ 内网 / 本机 / 元数据 / 解析到内网 → 403，按会话记、同主机去重、取走即清")

    out = await ask(port, f"CONNECT nas.home:{oport} HTTP/1.1\r\n{A}\r\n".encode())
    assert out.startswith(b"HTTP/1.1 200 Connection Established"), out
    r, w = await asyncio.open_connection("127.0.0.1", port)
    w.write(f"CONNECT nas.home:{oport} HTTP/1.1\r\n{A}\r\n".encode())
    await w.drain()
    head = await r.readuntil(b"\r\n\r\n")
    assert head.startswith(b"HTTP/1.1 200"), head
    w.write(b"hello")
    await w.drain()
    assert await asyncio.wait_for(r.read(100), 5) == b"echo:hello"
    w.close()
    print("✓ 允许名单主机：隧道双向通，连的是查过的 IP")

    seen.clear()
    out = await ask(port, (f"GET http://nas.home:{oport}/p?q=1 HTTP/1.1\r\nHost: nas.home\r\n{A}"
                           "Proxy-Connection: keep-alive\r\nAccept: */*\r\n\r\n").encode())
    assert out.startswith(b"HTTP/1.1 200 OK") and out.endswith(b"ok"), out
    req = seen[0].decode()
    assert req.startswith("GET /p?q=1 HTTP/1.1\r\n"), req
    assert "Proxy-Authorization" not in req and "Proxy-Connection" not in req and "Connection: close" in req, req
    assert "Accept: */*" in req
    out = await ask(port, f"GET https://x/ HTTP/1.1\r\n{A}\r\n".encode())
    assert out.startswith(b"HTTP/1.1 400"), out
    print("✓ 明文 http：改写成相对路径、去掉代理头、只转一个请求；非 http 绝对地址 → 400")

    # 有人想用公网地址：真解析结果是公网 → 放行（这里连不上外网，只看 pick 选的 IP）
    assert await g.pick("public.example", 443) == "93.184.216.34"
    assert await g.pick("8.8.8.8", 53) == "8.8.8.8"
    for bad in [("", 443), ("public.example", 0), ("public.example", 70000)]:
        try:
            await g.pick(*bad)
            raise AssertionError(bad)
        except egress.Refused:
            pass
    g.forget("a")
    await g.stop()
    srv.close()
    print("✓ 出网关卡测试全部通过")


asyncio.run(main())
