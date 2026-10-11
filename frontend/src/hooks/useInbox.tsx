import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { http } from "../lib/api";
import type { InboxItem, InboxSummary } from "../lib/types";

/** 收件箱未读：没有推送时的“有新的吗”（与 App 的 InboxNotifier 同一套规则，见 docs/protocol.md）。
 *  InboxProvider 挂在外壳上，是未读数的唯一来源：导航角标、横幅、Home 的“全部已读”都读它。
 *  节奏：页面可见时立刻问一次，之后每 POLL_MS 问一次；页面隐藏时不问。
 *  version 在摘要变化时 +1，Home 据此重拉卡片，页面不各自轮询。 */
const POLL_MS = 2 * 60 * 1000;
const EMPTY: InboxSummary = { unread: 0, latest: null };

/** 相对上一次是不是“来了新的”：最新一条换了且未读数变多。只读掉/忽略不算。 */
export const hasNewSince = (next: InboxSummary, prev: InboxSummary) =>
  !!next.latest && next.latest.id !== prev.latest?.id && next.unread > prev.unread;

type Inbox = {
  summary: InboxSummary;
  version: number;
  banner: InboxItem | null;
  dismissBanner: () => void;
  refresh: () => Promise<void>;
  markRead: (ids?: string[]) => Promise<void>;
};
const Ctx = createContext<Inbox | null>(null);

export function InboxProvider({ children }: { children: ReactNode }) {
  const [summary, setSummary] = useState<InboxSummary>(EMPTY);
  const [version, setVersion] = useState(0);
  const [banner, setBanner] = useState<InboxItem | null>(null);
  const prev = useRef<InboxSummary | null>(null); // null = 还没有基线

  const apply = useCallback((next: InboxSummary) => {
    const last = prev.current;
    prev.current = next;
    if (last && last.unread === next.unread && last.latest?.id === next.latest?.id) return;
    setSummary(next);
    if (!last) return; // 首次只当基线
    setVersion((v) => v + 1);
    if (hasNewSince(next, last)) setBanner(next.latest);
  }, []);

  const refresh = useCallback(async () => {
    try { apply(await http.get<InboxSummary>("/api/inbox")); } catch { /* 网络失败静默，下次再问 */ }
  }, [apply]);

  const markRead = useCallback(async (ids?: string[]) => {
    apply(await http.post<InboxSummary>("/api/inbox/read", ids ? { ids } : {}));
  }, [apply]);

  useEffect(() => {
    let timer: number | undefined;
    const start = () => { refresh(); timer ??= window.setInterval(refresh, POLL_MS); };
    const stop = () => { window.clearInterval(timer); timer = undefined; };
    const onVis = () => (document.hidden ? stop() : start());
    if (!document.hidden) start();
    document.addEventListener("visibilitychange", onVis);
    return () => { stop(); document.removeEventListener("visibilitychange", onVis); };
  }, [refresh]);

  // 横幅停 4 秒自己收起（与 App 的 Timing.bannerHold 一致）
  useEffect(() => {
    if (!banner) return;
    const id = window.setTimeout(() => setBanner(null), 4000);
    return () => window.clearTimeout(id);
  }, [banner]);

  // 标签页标题带未读数，切到别的标签也能看见
  useEffect(() => {
    const base = document.title.replace(/^\(\d+\+?\) /, "");
    document.title = summary.unread > 0 ? `(${summary.unread > 99 ? "99+" : summary.unread}) ${base}` : base;
  }, [summary.unread]);

  const dismissBanner = useCallback(() => setBanner(null), []);
  return <Ctx.Provider value={{ summary, version, banner, dismissBanner, refresh, markRead }}>{children}</Ctx.Provider>;
}

export function useInbox(): Inbox {
  const v = useContext(Ctx);
  if (!v) throw new Error("useInbox 需要在 InboxProvider 里使用");
  return v;
}
