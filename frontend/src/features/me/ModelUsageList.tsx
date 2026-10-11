import { formatMoney, formatTokens, type ModelUsage } from "../../lib/usage";

/** 按模型拆分的列表：设置页“用量与花费”和聊天里的“本对话用量”共用。 */
export default function ModelUsageList({ models, priced, currency }: { models: ModelUsage[]; priced: string[]; currency: string }) {
  return (
    <div className="list">
      {models.map((m) => (
        <div className="row" key={m.model}>
          <div className="row-body">
            <div className="row-title">{m.model}</div>
            <div className="row-sub">输入 {formatTokens(m.prompt_tokens)} · 输出 {formatTokens(m.completion_tokens)} · {m.calls} 次</div>
          </div>
          <span className="row-trail">{priced.includes(m.model) ? formatMoney(m.cost, currency) : "未定价"}</span>
        </div>
      ))}
    </div>
  );
}
