"""浏览器会话的“地区”（v2.68 CORE，和 v2.66 B35 工作区时钟同一思路）——唯一规则入口：网页看到的语言和时区。

以前 service.py 写死 locale=zh-CN、timezone_id=Asia/Shanghai：用户把 TIMEZONE 配成别处、或把回复语言改成英文，
网站照样按上海时间、中文页面给内容（订票时间、比价页面语言都跟用户对不上）。现在：

- 时区：后端每次 goto 带上 settings.timezone（和系统提示里的“现在是…”、工作区命令 TZ 同一个 TIMEZONE 配置）；
  没带 → 本服务环境变量 BROWSER_TZ / TIMEZONE → Asia/Shanghai。只认 IANA 名字，系统时区库里查得到才用。
- 语言：后端按“回复语言”设置给 BCP 47 代码（reply_language.browser_locale：auto/简体 → zh-CN，繁體 → zh-TW，英文 → en-US）；
  Playwright 用它同时设 navigator.language 和 Accept-Language。格式不对 → zh-CN。
- 只在新开浏览器上下文时生效；同名会话已开着、但设置变了（用户刚改了语言 / 时区）→ goto 时 needs_reopen 为真，
  service 存好登录状态后重开这个会话（goto 本来就要换页，丢的只是旧标签页和后退记录）。别的动作不重开。
"""
import os
import re
from dataclasses import dataclass

DEFAULT_LOCALE = "zh-CN"
DEFAULT_TZ = "Asia/Shanghai"
_LOCALE = re.compile(r"[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8}){0,2}")
_TZ = re.compile(r"[A-Za-z][A-Za-z0-9_+\-]*(?:/[A-Za-z0-9_+\-]+){0,2}")


@dataclass(frozen=True)
class Region:
    locale: str
    timezone_id: str

    def options(self) -> dict:
        """new_context 的参数。"""
        return {"locale": self.locale, "timezone_id": self.timezone_id}


def _tz_known(name: str) -> bool:
    try:
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
    except ImportError:  # pragma: no cover
        return True
    try:
        ZoneInfo(name)
        return True
    except ZoneInfoNotFoundError:
        try:  # 本机根本没有时区库（连 UTC 都查不到）：只能信格式，Chromium 自带 ICU 时区数据
            ZoneInfo("Asia/Shanghai")
            return False
        except ZoneInfoNotFoundError:
            return True
    except (ValueError, OSError):
        return False


def clean_tz(raw: object) -> str | None:
    s = raw.strip() if isinstance(raw, str) else ""
    return s if s and _TZ.fullmatch(s) and ".." not in s and _tz_known(s) else None


def clean_locale(raw: object) -> str | None:
    s = raw.strip().replace("_", "-") if isinstance(raw, str) else ""
    if not _LOCALE.fullmatch(s):
        return None
    head, *rest = s.split("-")
    # 规范写法：语言小写、地区大写（zh-cn → zh-CN；文字代码 Hant 首字母大写）
    tail = [p.upper() if len(p) == 2 else p.capitalize() if len(p) == 4 else p for p in rest]
    return "-".join([head.lower(), *tail])


def env_tz(env: dict | None = None) -> str:
    env = os.environ if env is None else env
    return clean_tz(env.get("BROWSER_TZ")) or clean_tz(env.get("TIMEZONE")) or DEFAULT_TZ


def pick(locale: object = None, timezone: object = None, env: dict | None = None) -> Region:
    """这次要的地区：请求里给的优先（认不出就当没给），否则环境变量 / 默认。"""
    return Region(clean_locale(locale) or DEFAULT_LOCALE, clean_tz(timezone) or env_tz(env))


def needs_reopen(current: Region | None, wanted: Region) -> bool:
    """已开着的会话地区和这次要的不同 → 重开（没记录 = 老会话，不动）。"""
    return current is not None and current != wanted
