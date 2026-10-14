import { useModelCatalog } from "../../hooks/useModelCatalog";
import { defaultEffort, effectiveEffort, effectiveModel, effortsFor, toEffortChoice } from "../../lib/models";
import { IconBrain } from "../../ui/icons";
import { Menu } from "../../ui/kit";

/** 思考强度钮（与 App EffortChip 同规则）：当前模型能调（≥2 档）才出现；点开是 kit Menu 选档（当前项打勾、一行说明），
 *  不再用原生 <select>（系统白底下拉，和界面割裂；用户 18:33）。选择归 useChat（effort / setEffort），这里只画和转发。 */
export default function EffortChip({ model, effort, onChange }: {
  model: string | null; effort: string | null; onChange: (choice: string | null) => void;
}) {
  const cat = useModelCatalog();
  const opt = cat ? effectiveModel(cat, model) : undefined;
  const levels = effortsFor(opt);
  if (!opt || !levels) return null;
  const eff = effectiveEffort(opt, effort)!;
  const def = defaultEffort(opt);
  const strong = eff.id !== def;
  return (
    <Menu label={`思考强度：${eff.label}`} align="left" triggerClass={`model-chip effort-chip ${strong ? "strong" : ""}`}
      trigger={<><IconBrain size={14} />{eff.label}</>}
      items={levels.map((l) => ({
        label: l.id === def ? `${l.label}（默认）` : l.label, hint: l.description, checked: l.id === eff.id,
        onSelect: () => { if (l.id !== eff.id) onChange(toEffortChoice(opt, l.id)); },
      }))} />
  );
}
