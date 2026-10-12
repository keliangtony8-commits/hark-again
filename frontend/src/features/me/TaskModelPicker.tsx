// 定时任务用哪个模型、想多深（= App features/me/task_model_picker.dart）：新建 / 编辑任务表单里，放在计划下面。
// 列表与规则全来自对话那一套（useModelCatalog + lib/models）：选默认存 null；只有一个模型且不能调思考 → 整块不出现；
// 换模型时原来选的档新模型没有 → 清回默认；思考那一行随模型出现（plan-body 的 rise 动效）。服务端规则 backend app/task_store.py。
import { useModelCatalog } from "../../hooks/useModelCatalog";
import { defaultEffort, effectiveEffort, effectiveModel, effortsFor, toChoice, toEffortChoice, type ModelCatalog } from "../../lib/models";
import type { ScheduledTask } from "../../lib/types";

export type TaskModel = { model: string | null; reasoning: string | null };

/** 详情页一句话：都是默认 → ""；否则“深度 · 思考 高”（= App taskModelLabel）。 */
export function taskModelLabel(t: Pick<ScheduledTask, "model" | "reasoning">, cat: ModelCatalog | null): string {
  if (!cat || (!t.model && !t.reasoning)) return "";
  const m = effectiveModel(cat, t.model);
  if (!m) return "";
  const levels = effortsFor(m);
  const eff = levels ? effectiveEffort(m, t.reasoning) : undefined;
  return [t.model ? m.label : null, eff && eff.id !== defaultEffort(m) ? `思考 ${eff.label}` : null].filter(Boolean).join(" · ");
}

export default function TaskModelPicker({ value, onChange }: { value: TaskModel; onChange: (v: TaskModel) => void }) {
  const cat = useModelCatalog();
  if (!cat) return null;
  const m = effectiveModel(cat, value.model);
  const levels = effortsFor(m);
  const selectable = cat.models.length > 1;
  if (!m || (!selectable && !levels)) return null;
  const eff = levels ? effectiveEffort(m, value.reasoning) : undefined;
  const pickModel = (id: string) => {
    const next = cat.models.find((x) => x.id === id);
    const keep = effortsFor(next)?.some((l) => l.id === value.reasoning);
    onChange({ model: toChoice(cat, id), reasoning: keep ? value.reasoning : null });
  };
  return (
    <div className="form-field"><span>用哪个模型</span>
      {selectable && (
        <div className="seg task-model" role="radiogroup" aria-label="模型">
          {cat.models.map((o) => (
            <button key={o.id} role="radio" aria-checked={o.id === m.id} className={`chip ${o.id === m.id ? "on" : ""}`}
              onClick={() => pickModel(o.id)}>{o.label}</button>
          ))}
        </div>
      )}
      {levels && eff && (
        <div className="plan-body" key={m.id}>
          <div className="seg" role="radiogroup" aria-label="思考强度">
            {levels.map((l) => (
              <button key={l.id} role="radio" aria-checked={l.id === eff.id} className={`chip ${l.id === eff.id ? "on" : ""}`}
                title={l.id === defaultEffort(m) ? `默认 · ${l.description ?? ""}` : l.description}
                onClick={() => onChange({ model: value.model, reasoning: toEffortChoice(m, l.id) })}>思考 {l.label}</button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
