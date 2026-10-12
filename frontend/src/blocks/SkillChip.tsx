import { Link } from "react-router-dom";
import type { SkillBlock } from "../lib/types";
import { IconSpark } from "../ui/icons";

/** v1.81 用户消息里 `$技能` 点名的技能：气泡上方一枚胶囊小标签，点开技能页。规则在后端 app/skill_mentions.py。 */
export default function SkillChip({ block }: { block: SkillBlock }) {
  return (
    <Link className="skill-chip" to="/me/skills" title={`这次按技能「${block.name}」做`}>
      <IconSpark size={12} /><span>{block.name}</span>
    </Link>
  );
}
