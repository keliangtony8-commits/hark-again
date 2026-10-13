"""真 Chromium 排版（v2.22，需要装了 playwright + chromium；没有就跳过）：python3 browser/test_render_chromium.py
直接调 service.render：PDF 字节 + 页数（含页脚）、中文能排、@page 横向尊重；网络资源（图片、样式表、脚本里的 fetch）
一个都没真的连出去，个数回报在 X-Render-Blocked；脚本不跑；PNG 宽度按 width、太长截到 RENDER_PNG_MAX_H；参数错 400 / 413。"""
import asyncio, io, os, sys
sys.path.insert(0, os.path.dirname(__file__))
os.environ.setdefault("BROWSER_TOKEN", "t")
try:
    import playwright  # noqa: F401
except ImportError:
    print("跳过：没装 playwright"); sys.exit(0)
import service
from fastapi import HTTPException

hits = []


async def main():
    async def spy(r, w):
        hits.append(await r.read(500)); w.write(b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n"); await w.drain(); w.close()
    srv = await asyncio.start_server(spy, "127.0.0.1", 0)
    port = srv.sockets[0].getsockname()[1]
    long_body = "".join(f"<p>第 {i} 段：期末报告正文，中文排版测试。</p>" for i in range(400))
    html = (f"<html><head><link rel=stylesheet href='http://127.0.0.1:{port}/a.css'></head><body><h1>期末报告</h1>"
            f"<img src='http://127.0.0.1:{port}/x.png'><script>document.title='ran';fetch('http://127.0.0.1:{port}/js')</script>"
            f"{long_body}</body></html>")
    r = await service.render(service.RenderIn(html=html))
    assert r.media_type == "application/pdf" and r.body[:5] == b"%PDF-", r.body[:20]
    assert r.headers["x-render-blocked"] == "2", r.headers  # css + img；脚本没跑所以没有 fetch
    try:
        from pypdf import PdfReader
        pages = PdfReader(io.BytesIO(r.body)).pages
        assert len(pages) >= 5, len(pages)
        text = pages[0].extract_text()
        assert "期末报告" in text and "1 / " in text, text[:200]  # 中文 + 页脚页码
        land = await service.render(service.RenderIn(html="<style>@page{size:A4 landscape}</style><p>横</p>", page_numbers=False))
        box = PdfReader(io.BytesIO(land.body)).pages[0].mediabox
        assert box.width > box.height, box
    except ImportError:
        print("（没装 pypdf，跳过页数检查）")
    png = await service.render(service.RenderIn(html="<body style='margin:0'><div style='height:300px'>图</div></body>", format="png", width=640))
    assert png.media_type == "image/png" and int.from_bytes(png.body[16:20], "big") == 640, png.body[:24]
    assert png.headers["x-render-cut"] == "0"
    tall = await service.render(service.RenderIn(html=f"<div style='height:{service.RENDER_PNG_MAX_H + 4000}px'>长</div>", format="png", width=320))
    assert service.png_height(tall.body) == service.RENDER_PNG_MAX_H and tall.headers["x-render-cut"] == "1"
    for bad, code in ((service.RenderIn(html="x", format="jpg"), 400), (service.RenderIn(html="x", paper="B5"), 400),
                      (service.RenderIn(html="x" * (service.RENDER_HTML_MAX + 1)), 413)):
        try:
            await service.render(bad); raise AssertionError(bad)
        except HTTPException as e:
            assert e.status_code == code, (e.status_code, code)
    await asyncio.sleep(0.3)
    assert hits == [], hits
    assert service.png_height(b"nope") == 0
    print("✓ 真 Chromium：PDF 有页码和中文、@page 横向、长图截断、网络资源一个没连出去、脚本不跑")
    await service._browser.close()
    await service._pw.stop()

asyncio.run(main())
