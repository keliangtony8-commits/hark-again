"""v2.92 §P 名字与头像——唯一规则入口：用户希望被怎么称呼、给助手取的名字、用户头像、首次见面的问候。

为什么存 app_settings（key="identity"）而不是 users 表：Toyuis 只有一个主人（登录用户名来自 .env 的 OWNER_USERNAME），
没有 users 表；为了三个字段建一张单行表只会多一处数据源。和 reply_language 一样不用迁移。

- display_name：用户希望被怎么称呼（None = 没说过；界面退回登录用户名）。
- assistant_name：用户给助手取的名字（None = 没取，就叫 brand.json 的产品名 Toyuis）。
- avatar：头像版本号（None = 没有头像，界面画纯色圆 + 首字母）。文件只有一份：DATA/identity/avatar（不带扩展名，类型存在 avatar_type）。
- greeted_in：首次问候所在的对话 id（None = 还没问候过）。首次问候由助手在聊天里问（不做表单引导页）：
  客户端在主聊天空白时调 POST /api/profile/greet，服务器建一段对话、落一条固定的助手消息（零模型成本）。
  之后在这段对话里，系统提示附一句“用户回答了就调 set_names”，直到存过名字或对话超过 ONBOARD_MESSAGES 条。
- named：用户在问候后答过（调过 set_names，或在“我的”里改过）——问候引导就此结束。
"""
import time
from dataclasses import dataclass, replace

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .blocks import text_to_blocks
from .models import AppSetting, Conversation, Message
from .storage import DATA
from .version import APP_NAME

KEY = "identity"
NAME_MAX = 20                 # 称呼 / 助手名最多几个字（够写“Tony”“小克”“阿尔弗雷德”，挡住整句话被存成名字）
AVATAR_MAX = 2 * 1024 * 1024  # 头像最大 2 MB（客户端会先缩到 512px，正常几十 KB）
AVATAR_DIR = DATA / "identity"
ONBOARD_MESSAGES = 6          # 问候对话超过这么多条消息还没答，就不再提醒模型（用户显然在聊别的）
GREETING_TITLE = "初次见面"


@dataclass(frozen=True)
class Identity:
    display_name: str | None = None
    assistant_name: str | None = None
    avatar: int | None = None
    avatar_type: str | None = None
    greeted_in: str | None = None
    named: bool = False

    @property
    def assistant(self) -> str:
        """助手现在叫什么：取过名用取的，没取就是产品名。"""
        return self.assistant_name or APP_NAME


def clean_name(raw: object) -> str | None:
    """名字清洗：去首尾空白和引号，空 → None（= 清除）；过长或多行抛 ValueError（文案可直接给用户/模型看）。"""
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise ValueError("名字要是文字")
    s = raw.strip().strip("\"'“”‘’「」『』《》").strip()
    if not s:
        return None
    if "\n" in s or len(s) > NAME_MAX:
        raise ValueError(f"名字最多 {NAME_MAX} 个字，而且只能一行")
    return s


async def get(db: AsyncSession) -> Identity:
    row = await db.get(AppSetting, KEY)
    v = row.value if row and isinstance(row.value, dict) else {}
    known = Identity.__dataclass_fields__
    return Identity(**{k: v[k] for k in known if k in v})


async def _save(db: AsyncSession, ident: Identity) -> Identity:
    value = {k: getattr(ident, k) for k in Identity.__dataclass_fields__}
    row = await db.get(AppSetting, KEY)
    if row is None:
        db.add(AppSetting(key=KEY, value=value))
    else:
        row.value = value
    await db.commit()
    return ident


_UNSET = object()


async def set_names(db: AsyncSession, display_name: object = _UNSET, assistant_name: object = _UNSET) -> Identity:
    """改称呼 / 助手名（没传的不动；传空 = 清除）。设置页和 set_names 工具共用；调过就算问候已答。"""
    cur = await get(db)
    changes: dict = {"named": True}
    if display_name is not _UNSET:
        changes["display_name"] = clean_name(display_name)
    if assistant_name is not _UNSET:
        name = clean_name(assistant_name)
        changes["assistant_name"] = None if name == APP_NAME else name  # 叫回产品名 = 没取名
    return await _save(db, replace(cur, **changes))


# ---------- 头像 ----------

def avatar_path():
    return AVATAR_DIR / "avatar"


def sniff(data: bytes) -> str | None:
    """按文件头认图片类型（不信客户端报的 Content-Type：App 的 multipart 一律报 octet-stream）。"""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


async def set_avatar(db: AsyncSession, data: bytes) -> Identity:
    if not data:
        raise ValueError("图片是空的")
    if len(data) > AVATAR_MAX:
        raise ValueError("头像不能超过 2 MB")
    content_type = sniff(data)
    if content_type is None:
        raise ValueError("头像只支持 PNG、JPEG、WebP 图片")
    AVATAR_DIR.mkdir(parents=True, exist_ok=True)
    tmp = AVATAR_DIR / "avatar.part"
    tmp.write_bytes(data)
    tmp.replace(avatar_path())  # 原子替换：读的人永远看到完整的一张
    return await _save(db, replace(await get(db), avatar=int(time.time() * 1000), avatar_type=content_type))


async def clear_avatar(db: AsyncSession) -> Identity:
    avatar_path().unlink(missing_ok=True)
    return await _save(db, replace(await get(db), avatar=None, avatar_type=None))


# ---------- 首次问候 ----------

def greeting(ident: Identity) -> str:
    """定稿开场（HANDOFF §P）：正式、不开玩笑，初次打招呼亲切。"""
    return (f"你好，我是 {ident.assistant}，很高兴为你服务。请问我该如何称呼你？"
            f"如果你愿意，也可以为我取一个名字；不取的话，我就继续叫 {ident.assistant}。")


def should_greet(ident: Identity) -> bool:
    return ident.greeted_in is None and not ident.named


async def greet(db: AsyncSession) -> str | None:
    """建问候对话并返回 id；已经问候过（或用户早在设置里填过名字）→ None。只在主聊天用（不属于任何项目）。"""
    ident = await get(db)
    if not should_greet(ident):
        return None
    conv = Conversation(title=GREETING_TITLE, title_source="fixed", project_id=None)
    db.add(conv)
    await db.flush()
    db.add(Message(conversation_id=conv.id, role="assistant", blocks=text_to_blocks(greeting(ident)), status="done"))
    await _save(db, replace(ident, greeted_in=conv.id))  # 同一次 commit：对话和“问候过”一起落库
    return conv.id


ONBOARD_LINE = ("【初次见面】这段对话开头你已经问过用户怎么称呼、要不要给你取名。用户在回答时，调 deferred_tool call set_names "
                "保存（只说了称呼就只传 display_name；给你取了名才传 assistant_name；说不用取名就不传它），然后用新称呼简短确认一句。"
                "用户没接这个话题、直接问别的，就照常回答，不要追问。")


async def onboarding_line(db: AsyncSession, conversation_id: str) -> str:
    """问候对话里、用户还没答时附在系统提示易变段的一句；其余情况空字符串（零 token）。"""
    ident = await get(db)
    if ident.named or ident.greeted_in != conversation_id:
        return ""
    n = await db.scalar(select(func.count()).select_from(Message).where(Message.conversation_id == conversation_id))
    return ONBOARD_LINE if (n or 0) <= ONBOARD_MESSAGES else ""


# ---------- 系统提示 / 接口 ----------

def persona(ident: Identity) -> str:
    """系统提示第一句：助手叫什么、用户希望被怎么称呼。只在改名时变，放稳定段不影响缓存命中。"""
    line = f"你是 {ident.assistant}，用户的私人助手。"
    if ident.assistant_name:
        line += f"“{ident.assistant_name}”是用户给你取的名字。"
    if ident.display_name:
        line += f"称呼用户为“{ident.display_name}”（需要称呼时用，别每句都叫）。"
    return line


def wire(ident: Identity, username: str) -> dict:
    return {
        "username": username,
        "display_name": ident.display_name,
        "assistant_name": ident.assistant_name,
        "assistant_default": APP_NAME,
        "avatar": f"/api/profile/avatar/{ident.avatar}" if ident.avatar else None,
        "greet": should_greet(ident),
    }


def changed_text(ident: Identity) -> str:
    """set_names 工具的结果文案。"""
    parts = [f"称呼：{ident.display_name or '（未设置，用登录名）'}", f"你的名字：{ident.assistant}"]
    return "已保存（我的 → 点名字也能改）。" + "；".join(parts)
