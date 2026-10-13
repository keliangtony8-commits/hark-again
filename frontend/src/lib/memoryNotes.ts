// 记忆笔记（v2.21）的纯逻辑 + 共享仓库，与 App models/memory_note.dart + memoryNotesProvider 同规则：
// 类别名、第一行、副标题、多词筛选（路径/标题/正文/类别名）、新建时的路径预览（人 → people/，地方 → locations/）。
import { useEffect, useSyncExternalStore } from "react";
import { http } from "./api";
import type { MemoryNote } from "./types";

export const NOTE_KINDS: Record<string, string> = {
  contact: "人", place: "地方", project: "项目", organization: "组织", interest: "兴趣", event: "事件", misc: "其他",
};
export const noteKindLabel = (k: string) => NOTE_KINDS[k] ?? NOTE_KINDS.misc;

export function noteFirstLine(body: string): string {
  for (const line of body.split("\n")) {
    const t = line.trim().replace(/^#+/, "").trim().replace(/^[-*]+/, "").trim();
    if (t) return t;
  }
  return "";
}

export function noteSubtitle(n: MemoryNote): string {
  const first = noteFirstLine(n.body);
  const line = !first || first === n.title ? (n.body.trim() ? n.path : "还没写内容") : first;
  return `${noteKindLabel(n.kind)} · ${line}`;
}

export function filterNotes(list: MemoryNote[], query: string): MemoryNote[] {
  const words = query.toLowerCase().split(/\s+/).filter(Boolean);
  if (!words.length) return list;
  return list.filter((n) => {
    const hay = `${n.path}\n${n.title}\n${n.body}\n${noteKindLabel(n.kind)}`.toLowerCase();
    return words.every((w) => hay.includes(w));
  });
}

export function notePathPreview(input: string, kind: string): string {
  let p = input.trim().replace(/\\/g, "/").replace(/^\/+/, "");
  if (p.toLowerCase().endsWith(".md")) p = p.slice(0, -3);
  p = p.split("/").map((s) => s.trim()).join("/");
  if (!p || p.includes("/")) return p;
  const folder = kind === "contact" ? "people" : kind === "place" ? "locations" : "";
  return folder ? `${folder}/${p}` : p;
}

export const notesSummary = (n: number) => (n ? `${n} 篇笔记` : "");

const PATH = "/api/memory-notes";
type Snap = { items: MemoryNote[]; loaded: boolean };
let snap: Snap = { items: [], loaded: false };
let inflight: Promise<void> | null = null;
const listeners = new Set<() => void>();
const set = (next: Partial<Snap>) => { snap = { ...snap, ...next }; listeners.forEach((l) => l()); };
const subscribe = (l: () => void) => { listeners.add(l); return () => { listeners.delete(l); }; };

function load(): Promise<void> {
  if (inflight) return inflight;
  inflight = http.get<MemoryNote[]>(PATH).then((items) => set({ items, loaded: true })).finally(() => { inflight = null; });
  return inflight;
}

export const noteStore = {
  reload: load,
  async create(body: Partial<MemoryNote>) { const x = await http.post<MemoryNote>(PATH, body); set({ items: [x, ...snap.items] }); return x; },
  async update(id: string, body: Partial<MemoryNote>) {
    const x = await http.patch<MemoryNote>(`${PATH}/${id}`, body);
    set({ items: snap.items.map((i) => (i.id === id ? x : i)) });
    return x;
  },
  async remove(id: string) { await http.del(`${PATH}/${id}`); set({ items: snap.items.filter((i) => i.id !== id) }); },
};

/** 订阅笔记列表；第一次用到时加载（老服务器没有接口 → 保持空）。 */
export function useMemoryNotes(): Snap & typeof noteStore {
  const s = useSyncExternalStore(subscribe, () => snap);
  useEffect(() => { if (!snap.loaded) void load().catch(() => set({ loaded: true })); }, []);
  return { ...s, ...noteStore };
}
