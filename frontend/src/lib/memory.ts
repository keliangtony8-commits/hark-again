// 记忆页的纯逻辑，与 App models/memory.dart 同规则：分类名与顺序、分类计数、多词搜索（含分类中文名）+ 分类筛选。
import type { Memory, MemoryBlock } from "./types";

/** 已知分类的中文名，顺序即显示顺序；不认识的分类原样显示、排在后面。 */
export const MEMORY_CATEGORIES: Record<string, string> = {
  profile: "关于你", food: "饮食", travel: "出行", work: "学习工作", shopping: "购物", general: "其他",
};
const ORDER = Object.keys(MEMORY_CATEGORIES);

export const categoryLabel = (c: string) => MEMORY_CATEGORIES[c] ?? c;

export function compareCategory(a: string, b: string): number {
  const rank = (c: string) => (ORDER.includes(c) ? ORDER.indexOf(c) : ORDER.length);
  return rank(a) - rank(b) || (a < b ? -1 : a > b ? 1 : 0);
}

export function categoryCounts(list: Memory[]): [string, number][] {
  const counts = new Map<string, number>();
  for (const m of list) counts.set(m.category, (counts.get(m.category) ?? 0) + 1);
  return [...counts.keys()].sort(compareCategory).map((c) => [c, counts.get(c)!]);
}

/** 空格分开的词都要命中（内容或分类中文名，不分大小写）；category=null 为全部；按分类分组，组内保持服务器顺序。 */
export function filterMemories(list: Memory[], query = "", category: string | null = null): [string, Memory[]][] {
  const words = query.toLowerCase().split(/\s+/).filter(Boolean);
  const groups = new Map<string, Memory[]>();
  for (const m of list) {
    if (category && m.category !== category) continue;
    const hay = `${m.content}\n${categoryLabel(m.category)}`.toLowerCase();
    if (!words.every((w) => hay.includes(w))) continue;
    groups.set(m.category, [...(groups.get(m.category) ?? []), m]);
  }
  return [...groups.keys()].sort(compareCategory).map((c) => [c, groups.get(c)!]);
}

/** GET/POST /api/memory-digest。text=null 表示还没生成过。 */
export type MemoryDigest = { text: string | null; generated_at: string | null; count: number; memories: number; stale: boolean };

/** 聊天里记忆卡的状态（= App models/memory.dart memoryCardState）：对照当前记忆列表推算，不存在块里。
 *  unknown 列表没到 · active 仍生效可撤销 · undone 已撤销/已恢复 · diverged 记忆后来被别处改了，只显示。 */
export type MemoryCardState = "unknown" | "active" | "undone" | "diverged";

export function memoryCardState(b: MemoryBlock, list: Memory[] | null): MemoryCardState {
  if (!list || b.items.length === 0) return "unknown";
  const byId = new Map(list.map((m) => [m.id, m]));
  const contents = new Set(list.map((m) => m.content));
  switch (b.action) {
    case "saved":
      return b.items.every((i) => !byId.has(i.id)) ? "undone" : "active";
    case "updated": {
      const now = b.items.map((i) => byId.get(i.id));
      if (now.some((m) => !m)) return "diverged";
      if (b.items.every((i, k) => now[k]!.content === i.previous)) return "undone";
      if (b.items.every((i, k) => now[k]!.content === i.content)) return "active";
      return "diverged";
    }
    case "forgotten":
      return b.items.every((i) => contents.has(i.content)) ? "undone" : "active";
  }
  return "unknown";
}
