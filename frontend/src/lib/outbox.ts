import { server } from "./api";
import type { Message } from "./types";

/**
 * 发件箱持久化（对应 App chat_cache 的 outbox.*）：本机还没进服务器的用户消息，
 * 按对话存在 localStorage：outbox.<对话id>，新对话 outbox.new.<范围>（main 或项目 id）；按服务器地址分开。
 * 只有 useChat 读写这里。读回来一律是“发送失败”，不自动补发（可能已经发过了，由用户决定）。
 * 存储出错一律吞掉：发件箱是锦上添花，不能把聊天弄崩。
 */
const PREFIX = "assistant.outbox.";
const key = (projectId: string | undefined, id: string | null) =>
  `${PREFIX}${server.get() || location.origin}|${id ?? `new.${projectId || "main"}`}`;

export const outbox = {
  load(projectId: string | undefined, id: string | null): Message[] {
    try {
      const raw = JSON.parse(localStorage.getItem(key(projectId, id)) ?? "[]");
      if (!Array.isArray(raw)) return [];
      return raw
        .filter((m) => typeof m?.id === "string" && Array.isArray(m?.blocks))
        .map((m) => ({ id: m.id, role: "user" as const, blocks: m.blocks, outbox: "failed" as const }));
    } catch { return []; }
  },

  save(projectId: string | undefined, id: string | null, unsent: Message[]) {
    try {
      const k = key(projectId, id);
      if (unsent.length === 0) localStorage.removeItem(k);
      else localStorage.setItem(k, JSON.stringify(unsent.map(({ id, blocks }) => ({ id, blocks }))));
    } catch { /* 配额满/隐私模式：放弃持久化 */ }
  },

  /** 对话被删时，它的发件箱一起删。 */
  drop(id: string) {
    try {
      for (const k of Object.keys(localStorage)) if (k.startsWith(PREFIX) && k.endsWith(`|${id}`)) localStorage.removeItem(k);
    } catch { /* 同上 */ }
  },

  /** 退出登录：清空全部。 */
  clear() {
    try {
      for (const k of Object.keys(localStorage)) if (k.startsWith(PREFIX)) localStorage.removeItem(k);
    } catch { /* 同上 */ }
  },
};

export const OUTBOX_GIVE_UP_MS = 45_000; // 与 App Timing.outboxGiveUp 一致
