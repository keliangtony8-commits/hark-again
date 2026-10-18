import { useParams } from "react-router-dom";
import { useSwr } from "../../hooks/useSwr";
import type { UsageReport } from "../../lib/usage";
import { Page, PageHeader } from "../../ui/kit";
import ModelUsageList from "./ModelUsageList";
import TopConversations from "./TopConversations";
import UsageCard from "./UsageCard";

/** 用量与花费（我的 → 用量卡的“查看用量”，或主页的预算提醒卡）。和 App /me/usage 同一页。 */
export default function UsageScreen() {
  return <Page header={<PageHeader title="用量与花费" back />}><UsageCard /></Page>;
}

/** 用量页的子页（/me/usage/:part，= App UsageDetailScreen）：conversations = 本月最花钱的对话全量，models = 本月按模型全量。读同一个 /api/usage（SWR，不多发请求）。 */
export function UsageDetailScreen() {
  const { part } = useParams();
  const convs = part === "conversations";
  const { data: r } = useSwr<UsageReport>("/api/usage");
  return (
    <Page header={<PageHeader title={convs ? "本月最花钱的对话" : "本月按模型"} back />}>
      {!r ? <div className="usage usage-skeleton" aria-busy="true"><div className="skeleton sk-chart" /></div>
        : <div className="usage fade-in">
            {convs ? <TopConversations report={r} title={false} /> : <ModelUsageList models={r.month.models} priced={r.priced} currency={r.currency} />}
          </div>}
    </Page>
  );
}
