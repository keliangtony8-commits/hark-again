import { IconBrain, IconSpark } from "../../ui/icons";
import { Page, PageHeader, stagger } from "../../ui/kit";
import { MeRows, type MeRow } from "./meRows";

/** “我的”里收拢入口的二级页（v2.81，= App me_hub.dart）：个人资料 = 记忆 + 技能。
 *  （v2.96 “账户”收拢页删除：连接器与保险箱合成“连接的账号”一页，“我的”直达。）
 *  原来的子页路由原样保留（深链照常能开）。加一个收拢页 = 在 HUBS 里加一项。 */
const HUBS = {
  profile: { title: "个人资料", line: "我记住的你，和教我做事的方法。", rows: [
    { to: "/me/memory", icon: IconBrain, title: "记忆" },
    { to: "/me/skills", icon: IconSpark, title: "技能" },
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
