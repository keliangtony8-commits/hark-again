// Pages 页的纯逻辑。与 App lib/features/me/page_library.dart 同规则。
import { isLive } from "../../lib/pages";
import type { SitePage } from "../../lib/types";

/** 在线 / 已下线两组，组内最近更新在前（同时间保持服务器顺序）。 */
export function groupPages(list: SitePage[]) {
  const sorted = list.map((p, i) => ({ p, i })).sort((a, b) => (b.p.updated ?? -Infinity) - (a.p.updated ?? -Infinity) || a.i - b.i).map((x) => x.p);
  return { live: sorted.filter(isLive), off: sorted.filter((p) => !isLive(p)) };
}

export function pagesSummary(list: SitePage[]): string {
  const g = groupPages(list);
  const parts = [g.live.length ? `${g.live.length} 个网页在线` : "", g.off.length ? `${g.off.length} 个已下线` : ""].filter(Boolean);
  return parts.length ? parts.join(" · ") : "还没有网页";
}

/** 起步按钮：开一段新对话把这句话发出去，由我来做页面。 */
export const PAGE_STARTERS = [
  { label: "行程页", prompt: "把我接下来的行程做成一个网页，方便发给同行的人" },
  { label: "邀请函", prompt: "帮我做一个聚会邀请函网页：时间、地点、怎么到" },
  { label: "个人主页", prompt: "帮我做一个简单的个人主页，先问我要放哪些内容" },
];
