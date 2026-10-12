"""request_env：任务缺一个命令环境变量（机器人 Token、第三方 API Key）时，在聊天里弹一张卡让用户填，
值直接存进保险箱（command_env.save），模型只拿到“存好了 $NAME”。对标 Hark 的 request_secret：密钥从不经过模型、
从不出现在聊天记录里。复用表单卡通道（Tool.form → loop._ask_form → ws form.reply），purpose=env：
值不写进卡片、不进历史（blocks.FormBlock 规则），只交给这里的 run。
- 无人值守（定时任务、后台运行）没人能填：不弹卡，告诉模型去请用户到「我的 → 保险箱 → 环境变量」里加。
- 已经有这个变量：照样弹卡（标题写“换个值”），用户填了就覆盖（Token 过期 / 换号是常见原因）。
- 变量名、值的校验只在 command_env（check_name / check_value / save），这里不重复规则。"""
from ... import command_env
from ..approvals import FormReply
from ..tools import ToolContext, ToolResult, nobody, tool

FIELD = "value"
REASON_MAX = 120


def request_card(name: str, reason: str, exists: bool) -> dict:
    """要变量卡（blocks.FormBlock，不含 id/state）。name 必须已经过 command_env.check_name。"""
    reason = (reason or "").strip()[:REASON_MAX]
    return {"type": "form", "purpose": "env", "title": f"{'换个值：' if exists else '需要'}{name}",
            "fields": [{"name": FIELD, "label": f"{name} 的值", "kind": "password",
                        "min_length": command_env.VALUE_MIN}],
            "action": "存进保险箱", **({"note": reason} if reason else {})}


async def _form(ctx: ToolContext, args: dict) -> dict | None:
    if ctx.ask is nobody:
        return None
    try:
        name = command_env.check_name(args.get("name") or "")
    except ValueError:
        return None  # run 里再报
    return request_card(name, args.get("reason") or "", name in await command_env.names(ctx.db))


@tool("request_env", "正在向你要环境变量",
      "沙盒里的程序要用一个用户自己的密钥（机器人 Token、第三方 API Key、数据库密码…）而系统提示里没列出这个环境变量，"
      "或者用户说旧值失效了时调用：在聊天里弹一张卡，用户把值填进去，直接存进保险箱，之后每条命令（含后台 / 常驻任务、"
      "定时脚本）都能用 $NAME 读到。你永远看不到值。绝不让用户把密钥发在聊天里；用户已经发了也别复述、别写进文件。"
      "网站登录用 browser_login，HTTP API 的密钥按域名注入（api_request）不用它。",
      {"type": "object", "properties": {
          "name": {"type": "string", "description": "环境变量名，大写字母 / 数字 / 下划线，如 TELEGRAM_BOT_TOKEN"},
          "reason": {"type": "string", "description": "一句话：拿它做什么、去哪儿弄（如：在 @BotFather 创建机器人后给的 Token）"}},
       "required": ["name", "reason"]}, form=_form)
async def request_env(ctx: ToolContext, name: str = "", reason: str = "", form: FormReply | None = None) -> ToolResult:
    try:
        var = command_env.check_name(name)
    except ValueError as e:
        return ToolResult(f"参数有误：{e}")
    if form is None:  # 只有没人能填时才走到这里（取消由内核处理）
        return ToolResult(f"现在是后台运行，没人能填。告诉用户到「我的 → 保险箱 → 环境变量」里添加 {var}，"
                          "加好后命令就能读到；别让用户把值发在聊天里。")
    value = form.values.get(FIELD, "")
    try:
        _, replaced = await command_env.save(ctx.db, var, value)
    except ValueError as e:  # 理由里不带值
        return ToolResult(f"没存成：{e}。可以再调一次 request_env 让用户重填。", failed=str(e))
    except RuntimeError as e:
        return ToolResult(f"没存成：{e}（服务器没配保险箱密钥 VAULT_KEY）。如实告诉用户。", failed=str(e))
    return ToolResult(f"用户已把 ${var} {'换成新值' if replaced else '存进保险箱'}。之后沙盒里的命令都能用 ${var} 读到"
                      f"（新启动的后台 / 常驻任务才会带上新值；已在跑的要重启）。输出里出现的值会显示成 [${var}]。")
