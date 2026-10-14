# 配置 Google / GitHub 一键授权（部署者做一次）

连接器页的“连接 Google / GitHub”需要服务器上有对应的 OAuth 应用。没配之前，连接器页不显示这两项，只给部署者一行“服务器还差一步：配置 … 授权”（点开是本文的摘要，回调地址与变量名由服务器实时给出）。

代码依据：服务商声明 `backend/app/connectors/providers.py`，授权流程 `backend/app/connectors/oauth.py`，配置项 `backend/app/config.py`。

## 0. 先确认 PUBLIC_URL

回调地址 = `<PUBLIC_URL>/api/oauth/callback`（`oauth.redirect_uri()`，只来自 `.env` 的 `PUBLIC_URL`）。

- 生产服务器：`.env` 里 `PUBLIC_URL=https://toyuis.itsllm.com`，回调地址就是
  **`https://toyuis.itsllm.com/api/oauth/callback`**
- 两边必须逐字一致（协议 https、域名、无多余路径）。改了域名就要同时改 `PUBLIC_URL` 和两个服务商后台里的回调地址。

## 1. GitHub OAuth App

1. 用你的 GitHub 账号打开 <https://github.com/settings/developers> → **OAuth Apps** → **New OAuth App**。
2. 填写：
   - Application name：`Toyuis`
   - Homepage URL：`https://toyuis.itsllm.com`
   - Authorization callback URL：`https://toyuis.itsllm.com/api/oauth/callback`
   - 不勾选 Enable Device Flow。
3. **Register application** → 页面上的 **Client ID** 抄下来 → **Generate a new client secret**，生成的 secret 只显示一次，立刻抄下来。
4. 权限范围不用在后台设置：授权时代码会请求 `repo`（读写仓库、Issue、PR）和 `read:user`（读取账户名）。
5. GitHub 的 OAuth 令牌不会过期，没有 refresh token；在 GitHub 上撤销授权后，连接器页会提示重新连接。

## 2. Google OAuth 客户端（测试模式）

1. 打开 <https://console.cloud.google.com/>，顶部选择或新建一个项目（例如 `toyuis`）。
2. **启用接口**：APIs & Services → Library，分别搜索并启用
   - Gmail API
   - Google Calendar API
   - Google Drive API
3. **同意屏幕**（Google Auth Platform / OAuth consent screen）：
   - Branding：应用名 `Toyuis`，用户支持邮箱和开发者联系邮箱填你自己的。
   - Audience：用户类型选 **External**，发布状态保持 **Testing**；在 **Test users** 里 **Add users**，加入你自己要连接的 Gmail 地址（测试模式下只有测试用户能授权）。
   - Data access（可选）：加入下面这些范围，授权页显示会更清楚；不加也能用，范围以代码请求的为准。
4. **创建客户端**：Clients（或 Credentials → Create credentials → OAuth client ID）
   - Application type：**Web application**，名称 `Toyuis`
   - Authorized redirect URIs：`https://toyuis.itsllm.com/api/oauth/callback`
   - Authorized JavaScript origins 不用填。
   - 创建后抄下 **Client ID** 和 **Client secret**（新版控制台的 secret 可能只在创建时完整显示，建议当场下载 JSON 备份）。
5. 代码请求的范围（`providers.py` 里 Google 的 `scopes`）：
   - `openid`、`email`：读取账户邮箱，作为连接器页显示的账户名
   - `https://www.googleapis.com/auth/gmail.modify`：读邮件、打标签、存草稿与发送（发送前助手一定先问你）
   - `https://www.googleapis.com/auth/calendar`：读写日历
   - `https://www.googleapis.com/auth/drive.readonly`：只读云端硬盘
   - 授权链接带 `access_type=offline` 和 `prompt=consent`，以拿到 refresh token。
6. **测试模式的限制**：发布状态为 Testing 时，Google 签发的 refresh token **7 天后失效**（只请求基本资料范围时除外；见 <https://developers.google.com/identity/protocols/oauth2#expiration>）。失效后服务器会在主页放一张“Google 连接已失效”提醒，去连接器页重新连接一次即可。授权页会显示“Google 尚未验证此应用”，因为是你自己的应用，点“继续”即可。

## 3. 填进 .env

在服务器的部署目录（生产为 `/opt/assistant`）编辑 `.env`，变量名与 `backend/app/config.py` 对应：

```dotenv
PUBLIC_URL=https://toyuis.itsllm.com

GOOGLE_CLIENT_ID=<Google 的 Client ID>
GOOGLE_CLIENT_SECRET=<Google 的 Client secret>
GITHUB_CLIENT_ID=<GitHub 的 Client ID>
GITHUB_CLIENT_SECRET=<GitHub 的 Client secret>
```

- 两个值都填了才算配置好（`Provider.configured`）；只配其中一家也可以，连接器页只显示配好的那家。
- 不要把真实的 ID / secret 提交进仓库，`.env` 只留在服务器上。

## 4. 重启后端与定时任务进程

`backend`（接口、授权回调）和 `worker`（定时任务里刷新令牌）都读 `.env`，两个都要重建：

```bash
cd /opt/assistant
docker compose up -d --force-recreate backend worker
docker compose logs --tail=50 backend   # 确认启动正常
```

## 5. 验证

1. 打开 App 或网页 → 我 → 连接器：配好的服务商出现在“账户”里，带“连接”按钮；“服务器还差一步”那一行消失（只配了一家时，这一行只列另一家）。
2. 点“连接 GitHub”→ GitHub 授权页 → Authorize → 自动回到连接器页，提示“已连接 GitHub”，这一行显示你的 GitHub 用户名。
3. 点“连接 Google”→ 选择测试用户里的那个 Gmail → 继续 → 勾选全部权限 → 回到连接器页显示你的邮箱。
4. 在聊天里试一句“看看我最近的 3 封邮件”“列出我的 GitHub 仓库”，确认助手能直接用。

常见错误：

| 现象 | 原因 |
|---|---|
| Google 显示 `redirect_uri_mismatch` | 后台的回调地址与 `<PUBLIC_URL>/api/oauth/callback` 不一致（检查 https、域名、末尾斜杠） |
| Google 显示 `access_denied` / 应用未完成验证 | 授权的账号不在 Test users 里 |
| GitHub 显示 “The redirect_uri MUST match the registered callback URL” | 同上，GitHub 只认注册时那一个回调地址 |
| 连接器页提示“授权链接已过期” | 授权页停留超过 10 分钟（state 有效期），回连接器页重新点一次 |
| 配好后连接器页仍没有这一项 | 没有重建容器，或 `.env` 里变量名拼错 / 值只填了一个 |
