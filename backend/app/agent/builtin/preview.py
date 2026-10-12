"""端口预览：把工作区电脑里跑着的网页服务给用户一条能打开的链接（规则都在 app/preview.py）。"""
from ... import preview
from ...blocks import PreviewBlock
from ..tools import ToolContext, ToolResult, tool


@tool("preview_port", "正在生成网页预览",
      "工作区电脑里的网页服务（网站、看板、小工具、API 文档页）跑起来后，用它给用户一张预览卡：用户在手机/电脑上点开就能看、能用，"
      f"链接 {preview.TTL_HOURS} 小时内有效。服务要先用 run_command background=true 启动并监听 0.0.0.0"
      "（如 python3 -m http.server 8000 --bind 0.0.0.0、npm run dev -- --host 0.0.0.0、flask run --host 0.0.0.0）。"
      "页面引用资源要用相对路径（以 / 开头的绝对路径会跳出预览；Vite 用 --base ./）；WebSocket（热更新、Streamlit/Gradio）会照常转发。"
      "不给 port 就列出正在监听的端口（只有一个时直接用它）。想自己先看一眼效果，用结果里的“内部地址”交给 browser_open。",
      {"type": "object", "properties": {
          "port": {"type": "integer", "minimum": 1, "maximum": 65535},
          "path": {"type": "string", "description": "打开时直接进的页面，如 docs 或 index.html；默认首页"},
          "title": {"type": "string", "description": "卡片标题：这是什么网页，如“记账小工具”"}}})
async def preview_port(ctx: ToolContext, port: int | None = None, path: str = "", title: str = "") -> ToolResult:
    try:
        if not port:
            st = await preview.listening(ctx.workspace)
            open_ = [p for p in st["ports"] if not p["loopback"]]
            if len(open_) != 1:
                if not st["running"]:
                    return ToolResult("电脑在休眠，没有在跑的服务。", failed="没有在跑的服务")
                return ToolResult(f"正在监听的端口：{preview.describe_ports(st['ports'])}。指定 port 再预览"
                                  "（只监听本机的要改绑 0.0.0.0）。", failed="" if open_ else "没有可预览的端口")
            port = open_[0]["port"]
        out = await preview.open_port(ctx.workspace, int(port), path.strip())
    except preview.PreviewError as e:
        return ToolResult(str(e), failed=str(e)[:80])
    block = PreviewBlock(workspace=ctx.workspace, port=out["port"], url=out["url"], title=title.strip()[:60] or None,
                         command=out["command"], expires_at=out["expires_at"])
    return ToolResult(f"预览卡已展示给用户（端口 {out['port']}，{out['command'][:80] or '未知程序'}），"
                      f"{preview.TTL_HOURS} 小时内有效；文字里不要再贴链接。"
                      f"内部地址（只给你自己的 browser_open 用，别发给用户）：{out['internal_url']}\n"
                      "服务停了或电脑休眠后链接会打不开，用户反馈打不开时先确认服务还在跑。",
                      [block.model_dump()])
