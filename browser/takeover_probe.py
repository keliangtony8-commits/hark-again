"""接管输入的复现页（测试共用，不进镜像）：顶层页 + 封闭 shadow root 里的跨源 iframe（= Cloudflare Turnstile 的结构），
iframe 里一个复选框，记录收到的每个 pointer / mouse 事件的关键字段（isTrusted、pointerType、buttons、detail、
screenX/clientX、时间戳），以及能看到的自动化痕迹（navigator.webdriver、UA）。

两个源：顶层 = http://127.0.0.1:<a>/，iframe = http://127.0.0.2:<b>/frame（不同站点 → 站点隔离下是独立进程 OOPIF）。
"""
import asyncio

TOP = """<!doctype html><meta charset=utf-8><title>接管复现</title>
<style>body{margin:0;font:14px sans-serif}#host{position:absolute;left:%(fx)dpx;top:%(fy)dpx}</style>
<p style="margin:8px">顶层页</p><div id=host></div>
<script>
// 封闭 shadow root 里的跨源 iframe：选择器 / element.click 都够不着，只能按页面坐标点
const root = document.getElementById('host').attachShadow({mode: 'closed'});
const f = document.createElement('iframe');
f.src = '%(frame)s'; f.width = %(fw)d; f.height = %(fh)d; f.style.border = '0';
root.appendChild(f);
window.__top = {webdriver: navigator.webdriver, ua: navigator.userAgent,
  brands: (navigator.userAgentData && navigator.userAgentData.brands || []).map(b => b.brand).join(','),
  outer: [outerWidth, outerHeight], inner: [innerWidth, innerHeight], screen: [screen.width, screen.height],
  screenXY: [screenX, screenY]};
</script>"""

FRAME = """<!doctype html><meta charset=utf-8><title>frame</title>
<style>body{margin:0;background:#f4f4f4;font:14px sans-serif}
label{position:absolute;left:%(cx)dpx;top:%(cy)dpx;display:flex;gap:6px;align-items:center}
input{width:24px;height:24px;margin:0}</style>
<label><input type=checkbox id=cb>我是人类</label>
<script>
window.__ev = [];
const keep = e => window.__ev.push({type: e.type, trusted: e.isTrusted, pt: e.pointerType || null, button: e.button,
  buttons: e.buttons, detail: e.detail, cx: e.clientX, cy: e.clientY, sx: e.screenX, sy: e.screenY,
  t: Math.round(e.timeStamp), target: e.target.id || e.target.tagName});
for (const t of ['pointerover', 'pointerenter', 'pointermove', 'pointerdown', 'pointerup', 'mouseover', 'mouseenter',
                 'mousemove', 'mousedown', 'mouseup', 'click', 'touchstart', 'touchend'])
  addEventListener(t, keep, true);
window.__env = {webdriver: navigator.webdriver, ua: navigator.userAgent};
</script>"""

# 复选框在顶层视口里的中心（iframe 左上 + 复选框中心）
FX, FY, FW, FH = 300, 200, 300, 80
CX, CY = 20, 28
BOX_CENTER = (FX + CX + 12, FY + CY + 12)


async def serve_probe():
    """起两个本地 HTTP 源，返回 (顶层 URL, 关闭函数)。"""
    async def frame_srv(r, w):
        await r.readuntil(b"\r\n\r\n")
        body = (FRAME % {"cx": CX, "cy": CY}).encode()
        w.write(b"HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\nConnection: close\r\nContent-Length: %d\r\n\r\n" % len(body) + body)
        await w.drain()
        w.close()

    fsrv = await asyncio.start_server(frame_srv, "127.0.0.2", 0)
    fport = fsrv.sockets[0].getsockname()[1]

    async def top_srv(r, w):
        await r.readuntil(b"\r\n\r\n")
        body = (TOP % {"fx": FX, "fy": FY, "fw": FW, "fh": FH, "frame": f"http://127.0.0.2:{fport}/frame"}).encode()
        w.write(b"HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\nConnection: close\r\nContent-Length: %d\r\n\r\n" % len(body) + body)
        await w.drain()
        w.close()

    tsrv = await asyncio.start_server(top_srv, "127.0.0.1", 0)
    url = f"http://127.0.0.1:{tsrv.sockets[0].getsockname()[1]}/"

    def close():
        fsrv.close()
        tsrv.close()
    return url, close


def probe_frame(page):
    for f in page.frames:
        if f.url.endswith("/frame"):
            return f
    return None
