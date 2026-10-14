"""回复语言（v2.67 BRAIN，对标 Hark 设置 → System preferences 里换语言）——唯一规则入口。

以前助手说什么语言全凭模型猜：用户说“以后都用英文回我”，只能记成一条记忆，相关记忆没被挑中时就又变回中文；
语音识别写死 zh，标题、记忆概括也跟着系统提示的中文走。现在一个设置管住所有“用户会读到的、模型写的字”：

- auto（默认）：跟随用户这句话的语言。不往系统提示加任何字（零 token，老用户的提示缓存不变）。
- zh-Hans / zh-Hant / en：固定语言。系统提示最后（VOLATILE 段末尾，离用户这句话最近）加一句（prompt_line），并在这一轮最后一条用户消息末尾补“（用英文回复。）”（nudge，只改请求副本；只靠系统提示小模型会被用户的语言带跑，v2.67 真测），自动标题、记忆概括同样照办
  （generated_line），语音识别用对应语种（asr_code）。
- 改法：我的 → 偏好设置（PATCH /api/preferences），或对话里说“以后都用英文回答”→ 模型调 set_reply_language。
  只这一句要别的语言（“这段翻成英文”）不改设置。
存在 app_settings 表 key="reply_language"（不用迁移）；不认识的值一律当 auto。
"""
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from .models import AppSetting

KEY = "reply_language"
AUTO = "auto"


@dataclass(frozen=True)
class Choice:
    code: str
    label: str      # 设置里显示的名字（用这门语言自己的写法）
    name: str       # 写进给模型的那句话里
    asr: str        # 语音识别语种


CHOICES: tuple[Choice, ...] = (
    Choice(AUTO, "跟随我的语言", "", "zh"),
    Choice("zh-Hans", "简体中文", "简体中文", "zh"),
    Choice("zh-Hant", "繁體中文", "繁体中文（台湾/香港用字）", "zh"),
    Choice("en", "English", "英文（English）", "en"),
)
CODES = tuple(c.code for c in CHOICES)
_BY_CODE = {c.code: c for c in CHOICES}
# 用户/模型常写的别名 → 规范代码（大小写、下划线不敏感）
_ALIASES = {
    "zh": "zh-Hans", "zh-cn": "zh-Hans", "zh-hans": "zh-Hans", "cn": "zh-Hans", "chinese": "zh-Hans", "中文": "zh-Hans",
    "简体中文": "zh-Hans", "简体": "zh-Hans",
    "zh-tw": "zh-Hant", "zh-hk": "zh-Hant", "zh-hant": "zh-Hant", "繁体中文": "zh-Hant", "繁體中文": "zh-Hant",
    "繁体": "zh-Hant", "繁體": "zh-Hant",
    "en": "en", "en-us": "en", "en-gb": "en", "english": "en", "英文": "en", "英语": "en",
    "auto": AUTO, "跟随": AUTO, "follow": AUTO, "default": AUTO, "自动": AUTO,
}


def normalize(raw: object) -> str | None:
    """任意写法 → 规范代码；认不出 → None（调用方决定是报错还是当 auto）。"""
    if not isinstance(raw, str):
        return None
    s = raw.strip().replace("_", "-")
    if s in _BY_CODE:
        return s
    return _ALIASES.get(s.lower()) or _ALIASES.get(s)


def choice(code: str) -> Choice:
    return _BY_CODE.get(code) or _BY_CODE[AUTO]


async def get(db: AsyncSession) -> str:
    row = await db.get(AppSetting, KEY)
    code = (row.value or {}).get("code") if row else None
    return code if code in _BY_CODE else AUTO


async def set(db: AsyncSession, raw: object) -> str:  # noqa: A001  模块内的 set，与内建同名无妨（调用写 reply_language.set）
    """存并 commit；认不出抛 ValueError（文案可直接给用户/模型看）。"""
    code = normalize(raw)
    if code is None:
        raise ValueError(f"不支持这种语言：{raw!r}。可选：{' / '.join(CODES)}")
    row = await db.get(AppSetting, KEY)
    if row is None:
        db.add(AppSetting(key=KEY, value={"code": code}))
    else:
        row.value = {"code": code}
    await db.commit()
    return code


def prompt_line(code: str) -> str:
    """系统提示里的一句；auto → 空（什么都不加）。"""
    c = choice(code)
    if c.code == AUTO:
        return ""
    return (f"【回复语言设置】用户设定了总是用{c.name}回复：这条回复必须用{c.name}写，哪怕他用别的语言提问；卡片里的文字也一样。"
            f"代码、命令、文件名、专有名词和引用的原文保持原样。"
            f"用户只是这一句要别的语言（比如“翻成日文”）就这一句照办；要以后都换成别的语言，调 set_reply_language。")


def nudge(history: list[dict], code: str) -> list[dict]:
    """固定语言时，给这一轮发给模型的最后一条用户消息末尾补一句“（用英文回复。）”——只改这次请求的副本，不落库。
    v2.67 真测：只写在系统提示里（哪怕放最后），step-3.7-flash 看到中文提问照样回中文；贴在用户这句话后面才稳。
    auto → 原样返回。content 是图文列表时追加一个 text 段。"""
    c = choice(code)
    if c.code == AUTO:
        return history
    i = next((k for k in range(len(history) - 1, -1, -1) if history[k].get("role") == "user"), None)
    if i is None:
        return history
    note = f"（用{c.name}回复。）"
    m = dict(history[i])
    content = m.get("content")
    if isinstance(content, list):
        m["content"] = [*content, {"type": "text", "text": note}]
    else:
        m["content"] = f"{content or ''}\n\n{note}"
    return [*history[:i], m, *history[i + 1:]]


def generated_line(code: str) -> str:
    """后台替用户写的短文本（对话标题、记忆概括）追加的一句；auto → 空（照原提示“用用户自己的语言”）。"""
    c = choice(code)
    return "" if c.code == AUTO else f"用{c.name}写。"


def name_or(code: str, default: str) -> str:
    """提示里写死了语言的地方（记忆概括“请用中文”）：固定语言 → 它的名字；跟随 → default。"""
    c = choice(code)
    return default if c.code == AUTO else c.name


def asr_code(code: str) -> str:
    return choice(code).asr


def wire(code: str) -> dict:
    return {"reply_language": code,
            "reply_languages": [{"code": c.code, "label": c.label} for c in CHOICES]}


def changed_text(code: str) -> str:
    """set_reply_language 工具的结果文案。"""
    c = choice(code)
    if c.code == AUTO:
        return "已改成跟随用户的语言：之后用户用什么语言写就用什么语言回。"
    return f"已设成总是用{c.name}回复（我的 → 偏好设置里也能改）。这条回复就用{c.name}。"
