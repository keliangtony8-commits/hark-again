// 记忆列表的全站共享仓库（= App core/resource.dart memoriesProvider）：记忆页和聊天里的记忆卡读同一份，
// 在卡片上撤销、在记忆页改，两边立刻一致；助手改了记忆（聊天流出现记忆卡）时 invalidate 重拉。
import { useEffect, useSyncExternalStore } from "react";
import { http } from "./api";
import type { Memory } from "./types";

const PATH = "/api/memories";
type Snap = { items: Memory[]; loaded: boolean; loading: boolean };
let snap: Snap = { items: [], loaded: false, loading: false };
let inflight: Promise<void> | null = null;
const listeners = new Set<() => void>();
const set = (next: Partial<Snap>) => { snap = { ...snap, ...next }; listeners.forEach((l) => l()); };
const subscribe = (l: () => void) => { listeners.add(l); return () => { listeners.delete(l); }; };

function load(): Promise<void> {
  if (inflight) return inflight;
  set({ loading: true });
  inflight = http.get<Memory[]>(PATH)
    .then((items) => set({ items, loaded: true }))
    .finally(() => { inflight = null; set({ loading: false }); });
  return inflight;
}

export const memoryStore = {
  /** 服务器那边变了（助手记住/改/忘了）：已经加载过才重拉，没人看就等第一次用到时再拉。 */
  invalidate() { if (snap.loaded || inflight) void load().catch(() => {}); },
  reload: load,
  async create(body: Partial<Memory>) { const x = await http.post<Memory>(PATH, body); set({ items: [x, ...snap.items] }); return x; },
  async update(id: string, body: Partial<Memory>) {
    const x = await http.patch<Memory>(`${PATH}/${id}`, body);
    set({ items: snap.items.map((i) => (i.id === id ? x : i)) });
    return x;
  },
  async remove(id: string) { await http.del(`${PATH}/${id}`); set({ items: snap.items.filter((i) => i.id !== id) }); },
};

/** 订阅记忆列表；第一次用到时加载。loaded=false 期间别据此下结论（记忆卡此时不给撤销键）。 */
export function useMemories(): Snap & typeof memoryStore {
  const s = useSyncExternalStore(subscribe, () => snap);
  useEffect(() => { if (!snap.loaded) void load().catch(() => {}); }, []);
  return { ...s, ...memoryStore };
}
