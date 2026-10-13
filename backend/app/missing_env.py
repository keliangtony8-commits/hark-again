"""命令因为缺一个“密钥类”环境变量失败 → 说给模型的话：唯一入口（v2.54，E2E 第十轮 B24）。

起因（l4）：weather.py 读 OPENWEATHER_KEY，没设就退出。模型没调 request_env，而是拿一把记忆里的“示例 Key”
直接去请求 OpenWeather（第三方收到一把不属于用户的凭据），401 后又让用户“把 Key 填给我”（等于在聊天里发密钥）。
Hark 的公开行为：缺密钥 → request_secret 卡，值不经过模型。

规则（只在命令失败时看输出）：
- 认得出的变量名：Python `KeyError: 'NAME'`（输出里有 environ / getenv）、Node `process.env.NAME`、
  shell `NAME: parameter not set` / `unbound variable`，以及“缺少 / 未设置 / missing / not set / is required /
  undefined …”前后紧挨着的 NAME；
- 只认像密钥的名字（含 KEY / TOKEN / SECRET / PASSWORD / PASSWD / PASS / APPID / CREDENTIAL / AUTH），
  别的变量（PORT、DEBUG）缺了不是用户要给的东西；系统变量（command_env.RESERVED）不认；
- 已经在保险箱里的不提（它其实注入了，失败是别的原因）。
refs（Codex / Gemini / deepseek-harness）都没有：开发者工具直接读本机环境 → 自己的规则。
"""
import re

SHOW = 3  # 一次最多点名几个变量

_SECRETY = re.compile(r"KEY|TOKEN|SECRET|PASSWORD|PASSWD|PASS|APPID|CREDENTIAL|AUTH")
_NAME = r"([A-Z][A-Z0-9_]{1,63})"
_PATTERNS = [
    re.compile(r"KeyError: ['\"]" + _NAME + r"['\"]"),                       # os.environ["X"]
    re.compile(r"process\.env\.\s*" + _NAME),                                  # Node
    re.compile(r"\$?\{?" + _NAME + r"\}?: (?:parameter (?:null or )?not set|unbound variable)"),  # shell
    re.compile(r"(?:缺少|缺|没有设置|没设置|未设置|没有配置|未配置|请设置|请先设置|需要设置|missing|Missing|MISSING|"
               r"set the|Set the|please set|Please set)\s*(?:环境变量|environment variable|env var|env)?\s*[`'\"$]?" + _NAME),
    re.compile(_NAME + r"[`'\"]?\s*(?:环境变量)?\s*(?:没有设置|没设置|未设置|为空|is not set|not set|is missing|"
               r"is required|is undefined|not found in (?:the )?environment|environment variable (?:is )?(?:not set|missing|required))"),
]


def names(output: str | None, reserved: frozenset = frozenset(), have: set | None = None) -> list[str]:
    """输出里提到“缺了”的密钥类变量名（去重保序）。"""
    text = output or ""
    found: dict[str, None] = {}
    for pat in _PATTERNS:
        for m in pat.finditer(text):
            n = m.group(1)
            if pat is _PATTERNS[0] and "environ" not in text and "getenv" not in text:
                continue  # 普通字典的 KeyError 不算
            if n in reserved or (have and n in have) or not _SECRETY.search(n):
                continue
            found[n] = None
    return list(found)


def note(output: str | None, reserved: frozenset = frozenset(), have: set | None = None) -> str:
    """附在失败命令结果后面的一段（带换行）；没认出 → 空。"""
    ns = names(output, reserved, have)[:SHOW]
    if not ns:
        return ""
    vars_ = "、".join(f"${n}" for n in ns)
    first = ns[0]
    return (f"⚠ 程序缺用户自己的密钥 {vars_}。下一步就直接调 request_env(name=\"{first}\", reason=\"一句话：拿它做什么、去哪儿申请\")（不用先 describe）"
            "弹卡让用户填（值直接进保险箱，你看不到），填好后重跑同一条命令。"
            "绝不拿示例 Key、文档 / 教程 / 网上找到的 Key 或自己编的值去试（那是别人的凭据），"
            "也别让用户把 Key 发在聊天里。改用别的办法（比如 web_search）给出答案时，说清楚不是这个程序跑出来的。\n")
