"""所有 OAuth 服务的声明。只写数据，不写流程。"""
from dataclasses import dataclass, field

from ..config import settings


@dataclass(frozen=True)
class Provider:
    id: str
    name: str
    desc: str
    logo: str                      # 用来取 favicon 的域名
    authorize_url: str
    token_url: str
    scopes: list[str]
    api_hosts: list[str]           # 这些域名的请求自动带上该连接的 Token
    userinfo_url: str
    account_field: str             # userinfo 里代表账户名的字段
    extra_auth_params: dict = field(default_factory=dict)
    aliases: tuple[str, ...] = ()  # 用户 / 模型可能用的别称（产品名、中文），connector_accounts.find 用
    console_url: str = ""          # 部署者去哪注册 OAuth 应用（连接器页“配置授权”引导、docs/oauth-setup.md）

    @property
    def env_names(self) -> tuple[str, str]:
        """.env 里这个服务商的两个变量名（config.py 字段 <id>_client_id / <id>_client_secret 的大写）。"""
        return f"{self.id.upper()}_CLIENT_ID", f"{self.id.upper()}_CLIENT_SECRET"

    @property
    def client_id(self) -> str:
        return getattr(settings, f"{self.id}_client_id", "")

    @property
    def client_secret(self) -> str:
        return getattr(settings, f"{self.id}_client_secret", "")

    @property
    def configured(self) -> bool:
        return bool(self.client_id and self.client_secret)


PROVIDERS: dict[str, Provider] = {p.id: p for p in [
    Provider(
        id="google", name="Google", desc="Gmail、日历、云端硬盘", logo="google.com",
        authorize_url="https://accounts.google.com/o/oauth2/v2/auth",
        token_url="https://oauth2.googleapis.com/token",
        scopes=["openid", "email",
                "https://www.googleapis.com/auth/gmail.modify",
                "https://www.googleapis.com/auth/calendar",
                "https://www.googleapis.com/auth/drive.readonly"],
        api_hosts=["gmail.googleapis.com", "www.googleapis.com", "content.googleapis.com"],
        userinfo_url="https://openidconnect.googleapis.com/v1/userinfo", account_field="email",
        extra_auth_params={"access_type": "offline", "prompt": "consent"},  # 拿 refresh_token
        aliases=("gmail", "googlecalendar", "calendar", "googledrive", "drive", "谷歌", "日历", "邮箱", "云端硬盘"),
        console_url="https://console.cloud.google.com/apis/credentials",
    ),
    Provider(
        id="github", name="GitHub", desc="仓库、Issue、PR", logo="github.com",
        authorize_url="https://github.com/login/oauth/authorize",
        token_url="https://github.com/login/oauth/access_token",
        scopes=["repo", "read:user"],
        api_hosts=["api.github.com"],
        userinfo_url="https://api.github.com/user", account_field="login",
        aliases=("git", "仓库"),
        console_url="https://github.com/settings/developers",
    ),
]}
