import type { AgentBlock } from "../lib/types";
import { IconSplit } from "../ui/icons";

/** v1.91 用户消息里 `@子助手`：气泡上方一枚胶囊小标签（不可点，结果在回复的子任务卡上）。规则在后端 app/agent_mentions.py。 */
export default function AgentChip({ block }: { block: AgentBlock }) {
  const name = block.name || "子助手";
  return (
    <span className="skill-chip is-static" title={`这件事交给了${name}`}>
      <IconSplit size={12} /><span>{name}</span>
    </span>
  );
}
