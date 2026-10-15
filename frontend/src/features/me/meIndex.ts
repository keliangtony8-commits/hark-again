/** “我的”页底部设置搜索的索引（v3.0，docs/devlog.md「2026-10-15 v3.0」）：全站唯一的设置搜索，只搜“某个设置 / 页面在哪”，
 *  不搜对话（对话在历史抽屉里搜）。App 同一份在 app/lib/features/me/me_index.dart——两份逐字对照（app/test/me_search_test.dart 会比，
 *  也会检查每个定位 id 在这边页面里真有 spot= / <Spot id=>）。改设置页的行 / 分区时顺手改这里。
 *  一行一条：e(id, 标题, 分区, 路由, 定位 id 或 null, "空格分隔的同义词")。分区决定结果行的图标和“所在位置”。 */
import { searchTerms } from "../../ui/kit";

export type MeSection = "me" | "profile" | "tasks" | "connectors" | "wallet" | "computer" | "usage" | "security" | "preferences" | "feedback" | "about";

export const SECTION_LABEL: Record<MeSection, string> = {
  me: "我的", profile: "个人资料", tasks: "定时任务", connectors: "连接的账号", wallet: "钱包", computer: "我的电脑",
  usage: "用量", security: "安全", preferences: "偏好设置", feedback: "反馈", about: "关于",
};

export type MeEntry = { id: string; title: string; section: MeSection; route: string; focus: string | null; keywords: string };

const e = (id: string, title: string, section: MeSection, route: string, focus: string | null, keywords: string): MeEntry => ({ id, title, section, route, focus, keywords });

export const ME_INDEX: MeEntry[] = [
  e("profile", "个人资料", "me", "/me/profile", null, "资料 记忆 技能"),
  e("memory", "记忆", "profile", "/me/memory", null, "记住 偏好 事实 人物 笔记 忘记"),
  e("skills", "技能", "profile", "/me/skills", null, "方法 步骤 做事 规则"),
  e("tasks", "定时任务", "me", "/me/tasks", null, "提醒 每天 定时 计划 自动 周期 面板 Home 闹钟"),
  e("connectors", "连接的账号", "me", "/me/connectors", null, "连接器 授权 OAuth Google GitHub Gmail 邮箱 MCP 保险箱 密钥 API Key 环境变量 网站登录 账户"),
  e("wallet", "钱包", "me", "/me/wallet", null, "付款 银行卡 信用卡 支付 结账 卡"),
  e("computer", "我的电脑", "me", "/me/computer", null, "电脑 服务器 沙盒 容器 状态 内存 端口 程序 文件"),
  e("pages", "Pages", "computer", "/me/pages", null, "网页 页面 分享 链接 发布 下线"),
  e("usage", "用量", "me", "/me/usage", null, "花费 费用 成本 账单 预算 token 钱 模型 自动选模型 按模型"),
  e("security", "安全", "me", "/me/security", null, "密码 登录 验证 账号安全"),
  e("preferences", "偏好设置", "me", "/me/preferences", null, "设置 外观 主题 语言"),
  e("feedback", "反馈", "me", "/me/feedback", null, "问题 报告 bug 点踩 差评"),
  e("about", "关于", "me", "/me/about", null, "版本 更新 服务器 介绍"),
  e("appearance", "外观", "preferences", "/me/preferences", "appearance", "深色 浅色 暗色 夜间 黑暗 主题 跟随系统 模式 dark light"),
  e("solid", "减少透明度", "preferences", "/me/preferences", "solid", "透明 毛玻璃 模糊 玻璃 对比度 不透明"),
  e("avatar-color", "头像颜色", "preferences", "/me/preferences", "avatar-color", "头像 颜色 色彩 换色"),
  e("reply-language", "回复语言", "preferences", "/me/preferences", "reply-language", "语言 中文 英文 English 日文 翻译"),
  e("two-factor", "两步验证", "security", "/me/security", "two-factor", "2FA 二次验证 双重验证 验证码 身份验证器 Authenticator"),
  e("recovery", "恢复码", "security", "/me/security", "two-factor", "备用码 恢复 两步验证 2FA"),
  e("sessions", "登录设备", "security", "/me/security", "sessions", "设备 退出其他设备 下线 会话 登录记录"),
  e("version", "版本", "about", "/me/about", "version", "版本号 更新 升级 请更新"),
  e("browser-logins", "浏览器登录", "computer", "/me/computer", "browser-logins", "网站 登录 cookie 浏览器 会话"),
  e("host", "主机模式", "computer", "/me/computer", "host", "服务器 主机 宿主机 权限 规则 root"),
  e("disk", "磁盘", "computer", "/me/computer", "disk", "空间 存储 清理 容量 装过的工具 文件"),
];

/** 结果行副标题：这一项在哪。 */
export const meWhere = (x: MeEntry) => SECTION_LABEL[x.section];

/** 点了去哪：带定位 id 时加 ?focus=（Page 读它，滚到那一项闪一下）。 */
export const meLocation = (x: MeEntry) => (x.focus ? `${x.route}?focus=${encodeURIComponent(x.focus)}` : x.route);

/** 按 query 筛选（= App searchMe，与对话搜索同一套 searchTerms 分词）：每个词都要命中“标题 + 位置 + 关键词”；
 *  排序：标题以第一个词开头 > 标题包含任一词 > 只命中位置 / 关键词，同档保持索引顺序。空查询返回空。 */
export function searchMe(query: string): MeEntry[] {
  const terms = searchTerms(query).map((t) => t.toLowerCase());
  if (!terms.length) return [];
  const rank = (x: MeEntry) => {
    const t = x.title.toLowerCase();
    return t.startsWith(terms[0]) ? 0 : terms.some((w) => t.includes(w)) ? 1 : 2;
  };
  return ME_INDEX
    .filter((x) => { const hay = `${x.title} ${meWhere(x)} ${x.keywords}`.toLowerCase(); return terms.every((w) => hay.includes(w)); })
    .map((x, i) => ({ x, i, r: rank(x) }))
    .sort((a, b) => a.r - b.r || a.i - b.i)
    .map((h) => h.x);
}
