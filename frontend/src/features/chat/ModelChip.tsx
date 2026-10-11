import { useModelCatalog } from "../../hooks/useModelCatalog";
import { effectiveModel, toChoice } from "../../lib/models";
import { IconBolt, IconSpark } from "../../ui/icons";

/** 输入框里的模型钮（与 App ModelChip 同规则）：两项点一下切换，更多项弹出小菜单；非默认用强调色。
 *  选择归 useChat（model / setModel），这里只画和转发。 */
export default function ModelChip({ model, onChange }: { model: string | null; onChange: (choice: string | null) => void }) {
  const cat = useModelCatalog();
  if (!cat || cat.models.length < 2) return null;
  const eff = effectiveModel(cat, model)!;
  const strong = eff.id !== cat.default;
  const pick = (id: string) => { if (id !== eff.id) onChange(toChoice(cat, id)); };
  if (cat.models.length > 2) {
    return (
      <label className={`model-chip ${strong ? "strong" : ""}`} title="这个对话用哪个模型">
        <IconSpark size={14} />
        <select value={eff.id} onChange={(e) => pick(e.target.value)} aria-label="模型">
          {cat.models.map((m) => <option key={m.id} value={m.id}>{m.label}</option>)}
        </select>
      </label>
    );
  }
  const next = cat.models.find((m) => m.id !== eff.id)!;
  return (
    <button className={`model-chip ${strong ? "strong" : ""}`} onClick={() => pick(next.id)}
      aria-label={`模型：${eff.label}，点按切换到${next.label}`} title={`切换到${next.label}`}>
      <span key={eff.id} className="model-chip-label">{strong ? <IconSpark size={14} /> : <IconBolt />}{eff.label}</span>
    </button>
  );
}
