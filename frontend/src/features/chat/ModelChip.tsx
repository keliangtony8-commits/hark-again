import { useModelCatalog } from "../../hooks/useModelCatalog";
import { autoHint, chipLabel, effectiveModel, toChoice } from "../../lib/models";
import { IconBolt, IconSpark, IconSwap } from "../../ui/icons";
import { Menu } from "../../ui/kit";

/** 输入框里的模型钮（与 App ModelChip 同规则）：两项点一下切换，更多项弹出 kit Menu（当前项打勾；不用原生 <select>）；非默认用强调色。
 *  选择归 useChat（model / setModel），这里只画和转发。 */
export default function ModelChip({ model, routed, onChange }: { model: string | null; routed?: string | null; onChange: (choice: string | null) => void }) {
  const cat = useModelCatalog();
  if (!cat || cat.models.length < 2) return null;
  const eff = effectiveModel(cat, model)!;
  const strong = eff.id !== cat.default;
  const label = chipLabel(cat, eff, routed);
  const pick = (id: string) => { if (id !== eff.id) onChange(toChoice(cat, id)); };
  if (cat.models.length > 2) {
    return (
      <Menu label={`模型：${label}`} align="left" triggerClass={`model-chip ${strong ? "strong" : ""}`}
        trigger={<>{eff.auto ? <IconSwap size={14} /> : <IconSpark size={14} />}<span className="chip-text">{label}</span></>}
        items={cat.models.map((m) => ({ label: m.label, hint: m.id === eff.id ? autoHint(cat, eff) ?? undefined : undefined,
          checked: m.id === eff.id, onSelect: () => pick(m.id) }))} />
    );
  }
  const next = cat.models.find((m) => m.id !== eff.id)!;
  return (
    <button className={`model-chip ${strong ? "strong" : ""}`} onClick={() => pick(next.id)}
      aria-label={`模型：${eff.label}，点按切换到${next.label}`} title={`切换到${next.label}`}>
      <span key={eff.id} className="model-chip-label">{strong ? <IconSpark size={14} /> : <IconBolt />}<span className="chip-text">{eff.label}</span></span>
    </button>
  );
}
