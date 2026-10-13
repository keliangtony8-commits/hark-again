import { agentChipLabel, agentChipSemantics } from "../lib/delegate";
import type { AgentBlock } from "../lib/types";
import { IconSplit } from "../ui/icons";

/** v1.91 用户消息里 `@子助手`：气泡上方一枚胶囊小标签（不可点，结果在回复的子任务卡上）。规则在后端 app/agent_mentions.py。
 *  v1.97 追问：在子任务卡上点“追问”发的消息，“追问 · 标题”（上下文不在了半透明）。 */
export default function AgentChip({ block }: { block: AgentBlock }) {
  return (
    <span className={`skill-chip is-static${block.gone ? " is-gone" : ""}`} title={agentChipSemantics(block)} aria-label={agentChipSemantics(block)}>
      <IconSplit size={12} /><span>{agentChipLabel(block)}</span>
    </span>
  );
}
