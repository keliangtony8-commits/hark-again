import { http } from "./api";

/** 聊天可选的模型（GET /api/catalog/models）；与 App models/resources.dart 的 ModelCatalog 同规则。 */
export type ModelOption = { id: string; label: string };
export type ModelCatalog = { default: string; models: ModelOption[] };

/** 对话的选择（null = 默认）→ 实际生效的那一项；别名已不在列表里也回落到默认（与后端 llm.chat_model 一致）。 */
export function effectiveModel(cat: ModelCatalog, choice: string | null | undefined): ModelOption | undefined {
  return cat.models.find((m) => m.id === choice) ?? cat.models.find((m) => m.id === cat.default) ?? cat.models[0];
}

/** 用户选了 id → 存到对话上的值：选默认就存 null（以后改默认会跟着变）。 */
export const toChoice = (cat: ModelCatalog, id: string): string | null => (id === cat.default ? null : id);

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
