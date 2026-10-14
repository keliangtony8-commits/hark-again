# 开发日志（全局决定）

> 本文件此前未提交进仓库（HANDOFF 引用的旧 devlog 留在旧沙盒里），自 v2.90.2 起重新开始记录。每次动手前先在这里写全局决定：放在哪、替换了什么、成本。

## 2026-10-14 v2.90.2 连接器按钮诚实化（HANDOFF §五 2a 中不需要 OAuth 凭据的部分）

**问题**：服务器 `.env` 没配 GOOGLE_/GITHUB_CLIENT_ID/SECRET 时，连接器页仍把 Google、GitHub 两行列出来（变淡、副标题“见 .env.example”）。用户看到的是“有这个功能但连不上”。

**决定**
1. **单一数据源 = 后端 `GET /api/connectors` 的 `status`**（判定只在 `app/connector_accounts.py`）。不新增接口。每项多一个 `setup`：服务器没配这个 OAuth 应用时给 `{console, callback, env}`（去哪注册、回调地址、要填的 .env 变量名），配好了为 `null`。回调地址只来自 `oauth.redirect_uri()`（即 `PUBLIC_URL`），客户端不再自己拼；变量名只来自 `Provider.env_names`；注册地址是 `providers.py` 里的数据 `console_url`。
2. **客户端只显示能用的**：`status == unconfigured` 的行整行不画（删掉原来的“变淡 + 见 .env.example”分支与 `Dimmed` 行）。已连接 / 授权失效的照常显示；若服务器后来删了配置（`setup != null`），这些行不再给“重新连接 / 重新授权”按钮，避免点了 400。
3. **缺配置时只给部署者一行**：账户区末尾一行“服务器还差一步：配置 Google / GitHub 授权”（列出缺的那些），点开是弹层引导：三步（去开发者后台创建应用、回调地址可复制、填 .env 后重启），完整步骤指向 `docs/oauth-setup.md`。一个都没配、也没连过时，账户区只剩这一行。
   - Toyuis 是单用户系统（`auth.py`：只有一个主人），能登录的就是部署者本人，所以“普通用户不显示、管理员显示一行”在现架构下等价于“登录者看到这一行”；分享出去的只读对话里没有连接器页，聊天连接卡对 unconfigured 本来就无按钮、助手也不会发（`refuse_connect`）。将来多用户时，只需在这一行外加角色判断。
4. **客户端删掉 `configured` 字段的使用**（App `Connector.configured`、Web `Connector.configured` 及其兜底推断），只认 `status` + `setup`。后端仍发 `configured`，仅为手机上还没更新的旧 APK 保留，协议里注明“新客户端不读”。
5. 文档：新增 `docs/oauth-setup.md`（GitHub OAuth App、Google OAuth 客户端测试模式 + 测试用户 + 用到的 scope、回调、.env、重启命令）；`docs/protocol.md` 记 `setup`；`.env.example` 注释指向该文档。

**替换/删除**：连接器页“未配置”变淡行（App `_AccountRow` 的 Dimmed 分支、Web `row-off` 分支）、两端 sortAccounts 的“未配置”第三档、两端 `configured` 兜底推断。
**成本**：无新接口、无迁移、无模型调用；列表每项多几十字节。
