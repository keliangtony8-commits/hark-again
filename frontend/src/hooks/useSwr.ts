import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react";
import { http } from "../lib/api";
import { swrCache, swrFetch, swrMutate, swrSubscribe } from "../lib/swr";

/** 读服务器数据的唯一 hook（规则见 lib/swr.ts，= App SwrNotifier / AsyncValue.swr）：
 *  - data：有缓存就立刻是缓存（首帧就是上次的内容），挂载 / 换 key 时后台静默重取，变了才换；
 *  - loading：只在“没缓存、还没出错”时为真 → 只有第一次才画骨架；
 *  - error：只在没数据时给（有数据时后台出错不打扰）；
 *  - reload()：重取一次（重试按钮、轮询、改完后对齐）；不抛，失败进 error；
 *  - mutate()：增删改后写进缓存，所有用这把 key 的组件一起变。
 *  key = null 表示先不取（比如还没选中对话）。默认 GET key；要兜底解析 / 别的取法给 fetcher。 */
export type Swr<T> = {
  data: T | undefined;
  error: Error | null;
  loading: boolean;
  reload: () => Promise<void>;
  mutate: (next: T | ((old: T | undefined) => T)) => void;
};

const noop = () => () => {};

export function useSwr<T>(key: string | null, fetcher?: () => Promise<T>): Swr<T> {
  const subscribe = useCallback((fn: () => void) => (key ? swrSubscribe(key, fn) : () => {}), [key]);
  const data = useSyncExternalStore(key ? subscribe : noop, () => (key ? swrCache.peek<T>(key) : undefined));
  const [failed, setFailed] = useState<{ key: string; error: Error } | null>(null);
  const fetchRef = useRef(fetcher);
  fetchRef.current = fetcher;

  const reload = useCallback(async () => {
    if (!key) return;
    try {
      await swrFetch<T>(key, fetchRef.current ?? (() => http.get<T>(key)));
      setFailed(null);
    } catch (e) {
      if (!swrCache.has(key)) setFailed({ key, error: e instanceof Error ? e : new Error(String(e)) });
    }
  }, [key]);

  useEffect(() => {
    if (!key) return;
    swrCache.read(key); // 标成最近用过
    void reload();
  }, [key, reload]);

  const mutate = useCallback((next: T | ((old: T | undefined) => T)) => { if (key) swrMutate<T>(key, next); }, [key]);
  const error = data === undefined && failed && failed.key === key ? failed.error : null;
  return { data, error, loading: !!key && data === undefined && !error, reload, mutate };
}
