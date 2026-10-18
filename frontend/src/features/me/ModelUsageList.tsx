import { ListGroup, ListRow } from "../../ui/kit";
import { cacheHitLabel, formatMoney, formatTokens, type ModelUsage } from "../../lib/usage";

/** 按模型拆分的列表：设置页“用量与花费”（limit 3，其余进 /me/usage/models）和聊天里的“本对话用量”（不传 limit，全量）共用。 */
export default function ModelUsageList({ models, priced, currency, limit }: { models: ModelUsage[]; priced: string[]; currency: string; limit?: number }) {
  return (
    <ListGroup>
      {(limit === undefined ? models : models.slice(0, limit)).map((m) => (
        <ListRow key={m.model} title={m.model}
          sub={[`输入 ${formatTokens(m.prompt_tokens)}`, `输出 ${formatTokens(m.completion_tokens)}`, `${m.calls} 次`,
            cacheHitLabel(m.cached_tokens, m.prompt_tokens)].filter(Boolean).join(" · ")}
          trail={priced.includes(m.model) ? formatMoney(m.cost, currency) : "未定价"} />
      ))}
    </ListGroup>
  );
}
