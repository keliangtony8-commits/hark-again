import { http } from "./api";

/** 聊天可选的模型（GET /api/catalog/models）；与 App models/resources.dart 的 ModelCatalog 同规则。 */
export type EffortLevel = { id: string; label: string; description?: string };
/** efforts / effort：能调思考强度的模型才有（后端 reasoning.catalog，从少到多 + 默认档）。 */
/** auto / routes：“自动”这一项（后端 model_router；每轮在 simple / complex 两档里挑）。 */
export type ModelOption = { id: string; label: string; efforts?: EffortLevel[]; effort?: string; auto?: boolean; routes?: { simple?: string; complex?: string } };
export type ModelCatalog = { default: string; models: ModelOption[] };

/** 对话的选择（null = 默认）→ 实际生效的那一项；别名已不在列表里也回落到默认（与后端 llm.chat_model 一致）。 */
export function effectiveModel(cat: ModelCatalog, choice: string | null | undefined): ModelOption | undefined {
  return cat.models.find((m) => m.id === choice) ?? cat.models.find((m) => m.id === cat.default) ?? cat.models[0];
}

export const labelOf = (cat: ModelCatalog, id: string): string => cat.models.find((m) => m.id === id)?.label ?? id;

/** 模型钮上的字：自动且知道上一轮用了谁 → “自动 · 快速”（与 App ModelCatalog.chipLabel 同规则）。 */
export function chipLabel(cat: ModelCatalog, eff: ModelOption, routed: string | null | undefined): string {
  return eff.auto && routed ? `${eff.label} · ${labelOf(cat, routed)}` : eff.label;
}

/** “自动”的一行说明（App autoHint 同）。 */
export function autoHint(cat: ModelCatalog, opt: ModelOption): string | null {
  const s = opt.routes?.simple, c = opt.routes?.complex;
  return opt.auto && s && c ? `简单的事用${labelOf(cat, s)}，复杂的用${labelOf(cat, c)}，每轮自动挑` : null;
}

/** 用户选了 id → 存到对话上的值：选默认就存 null（以后改默认会跟着变）。 */
export const toChoice = (cat: ModelCatalog, id: string): string | null => (id === cat.default ? null : id);

/** 这个模型可选的思考档；不足两档不给切换（与 App ModelCatalog.effortsFor 同规则）。 */
export function effortsFor(opt: ModelOption | undefined): EffortLevel[] | null {
  return opt?.efforts && opt.efforts.length > 1 ? opt.efforts : null;
}
/** 模型的默认档：给的默认不在列表里就取第一档。 */
export function defaultEffort(opt: ModelOption): string {
  const levels = opt.efforts ?? [];
  return levels.some((l) => l.id === opt.effort) ? opt.effort! : levels[0]?.id ?? "";
}
/** 对话的选择（null = 默认）→ 实际生效的档：这个模型没有那档也回默认（与后端 reasoning.resolve 一致）。 */
export function effectiveEffort(opt: ModelOption, choice: string | null | undefined): EffortLevel | undefined {
  const levels = opt.efforts ?? [];
  return levels.find((l) => l.id === choice) ?? levels.find((l) => l.id === defaultEffort(opt));
}
/** `/model 名字`（v1.89，同 App ModelCatalog.find）→ id；认不出 / 对上好几项 → null。
 *  大小写不敏感；“默认 / default” = 默认项；先 id、名字全等，再比开头（只对上一项才算）。 */
export function findModel(cat: ModelCatalog, query: string): string | null {
  const q = query.trim().toLowerCase();
  if (!q) return null;
  if (q === "默认" || q === "default") return cat.default;
  const exact = cat.models.find((m) => m.id.toLowerCase() === q || m.label.toLowerCase() === q);
  if (exact) return exact.id;
  const hits = new Set(cat.models.filter((m) => m.id.toLowerCase().startsWith(q) || m.label.toLowerCase().startsWith(q)).map((m) => m.id));
  return hits.size === 1 ? [...hits][0] : null;
}
export const findModelMiss = (cat: ModelCatalog, query: string) => `没有叫「${query.trim()}」的模型，可选：${cat.models.map((m) => m.label).join("、")}`;
/** /model 不接话（网页没有弹层，回一句）：现在用哪个 + 可选。 */
export const modelListNote = (cat: ModelCatalog, model: string | null | undefined) =>
  `现在用${effectiveModel(cat, model)?.label ?? "默认"}；可选：${cat.models.map((m) => m.label).join("、")}。打 /model 名字 直接换`;
export const modelNote = (cat: ModelCatalog, id: string) => `这个对话改用${labelOf(cat, id)}，下一轮起生效`;

/** 选了 id → 存到对话上的值：选默认存 null。 */
export const toEffortChoice = (opt: ModelOption, id: string): string | null => (id === defaultEffort(opt) ? null : id);

const KEY = "assistant.models";

/** 先给上次的（瞬开），再去服务器拿新的；拿不到就继续用缓存。 */
export function cachedModels(): ModelCatalog | null {
  try { return JSON.parse(localStorage.getItem(KEY) ?? "null"); } catch { return null; }
}
export async function fetchModels(): Promise<ModelCatalog> {
  const cat = await http.get<ModelCatalog>("/api/catalog/models");
  try { localStorage.setItem(KEY, JSON.stringify(cat)); } catch { /* 存不下就算了 */ }
  return cat;
}
