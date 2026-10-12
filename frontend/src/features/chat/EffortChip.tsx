import { useModelCatalog } from "../../hooks/useModelCatalog";
import { defaultEffort, effectiveEffort, effectiveModel, effortsFor, toEffortChoice } from "../../lib/models";
import { IconBrain } from "../../ui/icons";

/** 思考强度钮（与 App EffortChip 同规则）：当前模型能调（≥2 档）才出现，原生下拉选档，说明放在 title；非默认档用强调色。
 *  选择归 useChat（effort / setEffort），这里只画和转发。 */
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
    <label className={`model-chip effort-chip ${strong ? "strong" : ""}`} title={eff.description || "思考强度"}>
      <IconBrain size={14} />
      <select value={eff.id} aria-label={`思考强度：${eff.label}`}
        onChange={(e) => { if (e.target.value !== eff.id) onChange(toEffortChoice(opt, e.target.value)); }}>
        {levels.map((l) => (
          <option key={l.id} value={l.id} title={l.description}>{l.id === def ? `${l.label}（默认）` : l.label}</option>
        ))}
      </select>
    </label>
  );
}
