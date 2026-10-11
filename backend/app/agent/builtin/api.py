"""调用第三方 HTTP API。凭证由 credentials.resolve 按域名注入（OAuth 连接或保险箱）——模型只给出 URL，永远看不到密钥。
读（GET）直接执行；写（POST/PUT/PATCH/DELETE）会改动你的账户，需要你批准。
OAuth 连接失效（刷新被拒 / 对方 401）→ 主页提醒用户重连（connectors/oauth.expired），工具把原因告诉模型。"""
import json

import httpx

from ... import credentials
from ...connectors import oauth
from ..tools import ToolContext, ToolResult, tool

MAX_BODY = 10000
WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def _risk(args: dict) -> str | None:
    m = str(args.get("method", "GET")).upper()
    return f"用你的密钥向外部服务发送 {m} 请求" if m in WRITE_METHODS else None


@tool("api_request", "正在调用 API",
      "调用 HTTP API。已连接的账户（Google、GitHub 等）或保险箱里有该域名的密钥时，会自动附加认证（你看不到也不需要密钥）。"
      "返回状态码和响应正文（截断）。",
      {"type": "object", "properties": {
          "method": {"type": "string", "enum": ["GET", "POST", "PUT", "PATCH", "DELETE"], "default": "GET"},
          "url": {"type": "string"},
          "body": {"type": "object", "description": "JSON 请求体"},
          "headers": {"type": "object", "description": "额外请求头（不要放认证信息）"}},
       "required": ["url"]}, risk=_risk)
async def api_request(ctx: ToolContext, url: str, method: str = "GET", body: dict | None = None,
                      headers: dict | None = None) -> ToolResult:
    if not url.startswith("https://"):
        return ToolResult("只允许 https 地址。")
    hdrs = {k: str(v) for k, v in (headers or {}).items() if k.lower() not in {"authorization", "cookie"}}
    try:
        cred = await credentials.resolve(ctx.db, url)
    except oauth.ReconnectNeeded as e:
        return ToolResult(str(e))
    hdrs.update(cred.headers)
    async with httpx.AsyncClient(timeout=30, follow_redirects=False) as c:
        r = await c.request(method.upper(), url, headers=hdrs, json=body)
    if r.status_code == 401 and cred.connection is not None:  # token 还没到期就被拒：用户撤销了授权
        return ToolResult(str(await oauth.expired(ctx.db, cred.connection, "服务商不再接受这个授权（可能在对方那边被撤销了）")))

    try:
        text = json.dumps(r.json(), ensure_ascii=False, indent=1)
    except ValueError:
        text = r.text
    text = credentials.scrub(text, cred.scrub)  # 万一对方回显了密钥，也不让它进上下文
    used = f"（使用了{cred.source}）" if cred.source else "（未使用凭证）"
    return ToolResult(f"HTTP {r.status_code}{used}\n{text[:MAX_BODY]}")
