import { http } from "./api";

/** 聊天可选的模型（GET /api/catalog/models）；与 App models/resources.dart 的 ModelCatalog 同规则。 */
export type EffortLevel = { id: string; label: string; description?: string };
/** efforts / effort：能调思考强度的模型才有（后端 reasoning.catalog，从少到多 + 默认档）。 */
export type ModelOption = { id: string; label: string; efforts?: EffortLevel[]; effort?: string };
export type ModelCatalog = { default: string; models: ModelOption[] };

/** 对话的选择（null = 默认）→ 实际生效的那一项；别名已不在列表里也回落到默认（与后端 llm.chat_model 一致）。 */
export function effectiveModel(cat: ModelCatalog, choice: string | null | undefined): ModelOption | undefined {
  return cat.models.find((m) => m.id === choice) ?? cat.models.find((m) => m.id === cat.default) ?? cat.models[0];
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
