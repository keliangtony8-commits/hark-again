import { type ReactNode, createContext, createElement, useCallback, useContext, useEffect, useRef, useState, useSyncExternalStore } from "react";
import { useSwr } from "../../hooks/useSwr";
import { COMPUTER_POLL_IDLE_MS, COMPUTER_POLL_MS, type ComputerStatus, computerPath, liveServices } from "../../lib/computer";
import { sameJson, swrCache, swrMutate, swrSubscribe } from "../../lib/swr";

/** 一台电脑的状态（= App computerProvider）：电脑页 / 子页的各部件读同一份缓存（useSwr，键 = 路径）。
 *  v3.5.1（= App d8a2d73）：
 *  - ComputerPoll 包在页面外层：挂载时取一次 + 静默轮询（有普通后台任务 5 s；只有常驻服务 10 s；pollAlways 且运行中 5 s；页面隐藏时不问），
 *    自己因数据变化重渲染时 children 是同一个元素，不往下传；
 *  - 每个部件 / 每一行用 useComputerSelect 只取自己显示的那几个值（JSON 相同就返回旧值），一次轮询只重渲染真变了的行。 */
export type ComputerCtl = { s: ComputerStatus | null | undefined; set: (v: ComputerStatus) => void; load: () => Promise<void> };

/** 这次该隔多久问一次；null = 不用问（= App _ComputerPollState._every）。 */
export function computerPollMs(s: ComputerStatus, pollAlways: boolean): number | null {
  if (s.running_jobs.length > 0) return COMPUTER_POLL_MS;
  if (liveServices(s) > 0) return COMPUTER_POLL_IDLE_MS;
  if (pollAlways && s.sandbox.state === "running") return COMPUTER_POLL_MS;
  return null;
}

const LoadCtx = createContext<() => Promise<void>>(async () => {});

/** 重取一次（取消任务、重启服务后对齐）。值稳定，不因轮询重渲染。 */
export const useComputerLoad = () => useContext(LoadCtx);

/** 写入新状态（重启、清理接口直接回新状态）。 */
export const setComputer = (ws: string, v: ComputerStatus) => swrMutate<ComputerStatus>(computerPath(ws), v);

/** 点击时读一眼当前状态（不订阅）。 */
export const peekComputer = (ws: string) => swrCache.peek<ComputerStatus>(computerPath(ws));

export function ComputerPoll({ ws, pollAlways = false, children }: { ws: string; pollAlways?: boolean; children: ReactNode }) {
  const { data, reload } = useSwr<ComputerStatus>(computerPath(ws));
  const ms = data ? computerPollMs(data, pollAlways) : null;
  useEffect(() => {
    if (ms == null) return;
    const id = setInterval(() => { if (!document.hidden) void reload(); }, ms);
    return () => clearInterval(id);
  }, [ms, reload]);
  return createElement(LoadCtx.Provider, { value: reload }, children);
}

/** 只订阅 pick 出来的值：缓存换了新对象、但 pick 结果 JSON 相同 → 返回旧值，组件不重渲染。
 *  pick 依赖的外部参数（行 id）在组件一生里不变（行按 id 做 key）。 */
export function useComputerSelect<T>(ws: string, pick: (s: ComputerStatus | undefined) => T): T {
  const key = computerPath(ws);
  const pickRef = useRef(pick);
  pickRef.current = pick;
  const memo = useRef<{ key: string; src: unknown; out: T } | null>(null);
  const subscribe = useCallback((fn: () => void) => swrSubscribe(key, fn), [key]);
  const get = () => {
    const src = swrCache.peek<ComputerStatus>(key);
    const m = memo.current;
    if (m && m.key === key && m.src === src) return m.out;
    const out = pickRef.current(src);
    const keep = m && m.key === key && sameJson(m.out, out);
    memo.current = { key, src, out: keep ? m.out : out };
    return memo.current.out;
  };
  return useSyncExternalStore(subscribe, get);
}

/** 整份状态（子页里的整节用；undefined = 加载中，null = 拿不到且没有旧数据）。 */
export function useComputer(ws: string): ComputerCtl {
  const { data, error, reload, mutate } = useSwr<ComputerStatus>(computerPath(ws));
  return { s: data ?? (error ? null : undefined), set: mutate, load: reload };
}

/** 这一块是不是“滚过之后才出来的”（= App builtLate）：所在页已经滚过就不放入场动画 / 细条长出，直接画终态。挂载时定一次。 */
export function useLate(): boolean {
  const [late] = useState(() => (document.querySelector<HTMLElement>(".page.computer-page")?.scrollTop ?? 0) > 0);
  return late;
}
