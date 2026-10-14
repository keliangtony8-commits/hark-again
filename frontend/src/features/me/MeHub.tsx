import { IconBrain, IconLock, IconPlug, IconSpark } from "../../ui/icons";
import { Page, PageHeader, stagger } from "../../ui/kit";
import { MeRows, type MeRow } from "./meRows";

/** “我的”里收拢入口的二级页（v2.81，= App me_hub.dart）：个人资料 = 记忆 + 技能；账户 = 连接器 + 保险箱。
 *  原来的子页路由原样保留（深链照常能开）。加一个收拢页 = 在 HUBS 里加一项。 */
const HUBS = {
  profile: { title: "个人资料", line: "我记住的你，和教我做事的方法。", rows: [
    { to: "/me/memory", icon: IconBrain, title: "记忆" },
    { to: "/me/skills", icon: IconSpark, title: "技能" },
  ] },
  accounts: { title: "账户", line: "我替你登录和调用的地方：一键授权的账号、MCP 服务器，以及加密保存的 API Key 和网站登录。", rows: [
    { to: "/me/connectors", icon: IconPlug, title: "连接的账号" },
    { to: "/me/vault", icon: IconLock, title: "密钥与网站登录" },
  ] },
} satisfies Record<string, { title: string; line: string; rows: MeRow[] }>;

export type MeHubKind = keyof typeof HUBS;

export default function MeHub({ hub }: { hub: MeHubKind }) {
  const h = HUBS[hub];
  return (
    <Page header={<PageHeader title={h.title} back />}>
      <p className="desc sub-line enter">{h.line}</p>
      <div className="enter" style={stagger(1)}><MeRows rows={h.rows} /></div>
    </Page>
  );
}
