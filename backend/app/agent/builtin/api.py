"""调用第三方 HTTP API。凭证由 credentials.resolve 按域名注入（OAuth 连接或保险箱）——模型只给出 URL，永远看不到密钥。
读（GET）直接执行；写（POST/PUT/PATCH/DELETE）会改动你的账户，需要你批准。
OAuth 连接失效（刷新被拒 / 对方 401）→ 主页提醒用户重连（connectors/oauth.expired），工具把原因告诉模型。"""
import json

import httpx

from ... import api_keys, connector_accounts, credentials, web_guard
from ...connectors import oauth
from ..approvals import FormReply
from ..tools import ToolContext, ToolResult, nobody, tool

MAX_BODY = 10000
WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def _risk(args: dict, ctx=None) -> str | None:
    m = str(args.get("method", "GET")).upper()
    return f"用你的密钥向外部服务发送 {m} 请求" if m in WRITE_METHODS else None


@tool("api_request", "正在调用 API",
      "调用 HTTP API。已连接的账户（Google、GitHub 等）或保险箱里有该域名的密钥时，会自动附加认证（你看不到也不需要密钥）。"
      "服务要用户自己的 API Key 而还没有时，先 connect_api_key 让用户填。"
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
    try:
        async with web_guard.client(timeout=30, follow_redirects=False) as c:
            r = await c.request(method.upper(), url, headers=hdrs, json=body, params=cred.params or None)
    except web_guard.Blocked as e:
        return ToolResult(str(e), failed=str(e))
    except httpx.HTTPError as e:  # 错误里可能带着拼好 ?appid=<Key> 的网址
        msg = credentials.scrub(f"请求没发出去：{type(e).__name__} {e}", cred.scrub)[:300]
        return ToolResult(msg, failed="请求失败")
    if r.status_code == 401 and cred.connection is not None:  # token 还没到期就被拒：用户撤销了授权
        return ToolResult(str(await oauth.expired(ctx.db, cred.connection, "服务商不再接受这个授权（可能在对方那边被撤销了）")))

    try:
        text = json.dumps(r.json(), ensure_ascii=False, indent=1)
    except ValueError:
        text = r.text
    text = credentials.scrub(text, cred.scrub)  # 万一对方回显了密钥，也不让它进上下文
    used = f"（使用了{cred.source}）" if cred.source else "（未使用凭证）"
    hint = "" if cred.source else await connector_accounts.missing_hint(ctx.db, url)  # v2.36：该发连接卡就说
    if r.status_code in (401, 403) and cred.connection is None:
        hint += api_keys.rejected_hint(cred.source, hint)  # v2.52：没 Key / Key 失效 → connect_api_key
    return ToolResult(f"HTTP {r.status_code}{used}\n{text[:MAX_BODY]}{hint}")


# ---- v2.52 接上用户自己的 API Key（规则只在 app/api_keys.py） ----
KEY_FIELD = "key"
REASON_MAX = 120


def key_card(name: str, hosts: list[str], reason: str, replacing: bool) -> dict:
    """要 Key 的表单卡（blocks.FormBlock purpose=token：值不进卡片、不进历史，只交给这次 connect）。"""
    note = (reason or "").strip()[:REASON_MAX] or f"在 {name} 的控制台 / 开发者设置里申请的 API Key"
    return {"type": "form", "purpose": "token", "title": f"{'给' + name + '换一把新 Key' if replacing else '连接 ' + name + ' 需要 API Key'}",
            "site": hosts[0], "note": note, "action": "连接",
            "fields": [{"name": KEY_FIELD, "label": "API Key", "kind": "password", "min_length": api_keys.VALUE_MIN}]}


async def _key_form(ctx: ToolContext, args: dict) -> dict | None:
    if ctx.ask is nobody:
        return None
    try:
        hosts = api_keys.check_hosts(args.get("hosts") or [])
        api_keys.check_scheme(args.get("header_name") or "", args.get("header_prefix"), args.get("query_param") or "")
        name = api_keys.clean_name(args.get("service") or "", hosts)
        api_keys.check_verify_url(args.get("verify_url") or "", hosts)
    except api_keys.ConnectError:
        return None  # run 里再报（不弹一张注定存不进去的卡）
    return key_card(name, hosts, args.get("reason") or "", await api_keys.existing(ctx.db, hosts) is not None)


@tool("connect_api_key", "正在接上 API Key",
      "用户要用一个需要他自己 API Key 的服务（天气、地图、翻译、AI 接口、记账/笔记 App 的开放接口…）而保险箱里还没有，"
      "或 api_request 说 Key 被拒 / 失效时调用：弹一张卡让用户亲手填 Key，按你给的带法绑到这个服务的域名，先用 verify_url 真调一次，"
      "通过了才算接好；之后 api_request 发往这些域名会自动带上。你永远看不到 Key；绝不让用户把 Key 发在聊天里。"
      "带法照服务文档：默认 Authorization: Bearer；x-api-key 这类给 header_name（前缀不要就 header_prefix=\"\"）；"
      "Key 放网址参数的（OpenWeather appid、高德 key）给 query_param。GitHub / Google 这类有连接器的用 connector_accounts；"
      "沙盒命令里要用的 Key 用 request_env。",
      {"type": "object", "properties": {
          "service": {"type": "string", "description": "服务名，显示在卡上和保险箱里，如 OpenWeather"},
          "hosts": {"type": "array", "items": {"type": "string"}, "description": f"Key 只发往这些 API 域名（含子域名），最多 {api_keys.HOSTS_MAX} 个，如 [\"api.openweathermap.org\"]"},
          "reason": {"type": "string", "description": "一句话：拿它做什么、去哪儿申请（显示在卡上）"},
          "header_name": {"type": "string", "description": "放 Key 的请求头，默认 Authorization"},
          "header_prefix": {"type": "string", "description": "请求头里 Key 前面的字，默认 \"Bearer \"；不要前缀传 \"\""},
          "query_param": {"type": "string", "description": "Key 放网址参数时的参数名（如 appid）；给了就不用请求头"},
          "verify_url": {"type": "string", "description": "强烈建议：这个服务一个便宜的只读 GET 地址（https，在 hosts 里，不含 Key），用来确认 Key 能用"}},
       "required": ["service", "hosts", "reason"]}, form=_key_form, deferred=True)
async def connect_api_key(ctx: ToolContext, service: str = "", hosts: list | None = None, reason: str = "",
                          header_name: str = "", header_prefix: str | None = None, query_param: str = "",
                          verify_url: str = "", form: FormReply | None = None) -> ToolResult:
    try:
        hs = api_keys.check_hosts(hosts or [])
        api_keys.check_scheme(header_name, header_prefix, query_param)
        name = api_keys.clean_name(service, hs)
        api_keys.check_verify_url(verify_url, hs)
    except api_keys.ConnectError as e:
        extra = "改用 connector_accounts。" if e.kind == "oauth" else "改好参数再调。"
        return ToolResult(f"没弹卡：{e} {extra}", failed="参数不对")
    if form is None:  # 只有没人能填时才走到这里（取消由内核处理）
        return ToolResult(f"现在是后台运行，没人能填 Key。告诉用户到「我的 → 保险箱 → API Key」里添加 {name}"
                          f"（域名 {'、'.join(hs)}），加好后会自动带上；别让用户把 Key 发在聊天里。", failed="没人能填 Key")
    try:
        c = await api_keys.connect(ctx.db, name, form.values.get(KEY_FIELD, ""), hs, header_name=header_name,
                                   header_prefix=header_prefix, query_param=query_param, verify_url=verify_url)
    except api_keys.ConnectError as e:
        hint = ("可能是 Key 填错了，或带法（请求头 / 前缀 / 网址参数）和服务文档不一致：先核对带法；"
                "带法没错就问用户要不要再填一次，别反复弹卡。" if e.kind == "rejected" else "")
        return ToolResult(f"没接成：{e}{hint}", failed="Key 被拒" if e.kind == "rejected" else "没存成",
                          detail=name)
    except RuntimeError as e:
        return ToolResult(f"没存成：{e}（服务器没配保险箱密钥 VAULT_KEY）。如实告诉用户。", failed=str(e))
    return ToolResult(api_keys.connected_text(c), detail=f"接上 {c.secret.name}")
