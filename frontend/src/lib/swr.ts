// 全站唯一的“先给旧数据、后台再拉新的”（stale-while-revalidate）缓存。规则 = App lib/core/swr.dart，两端一致：
//  1. 第一次没有数据才显示骨架；之后再进页面（切页、开弹层、返回）首帧就是上次的数据，后台静默重取，变了才换。
//  2. 有数据时后台出错 → 继续显示旧数据，不打扰；没数据时出错 → 页面显示“加载失败 + 重试”。
//  3. 缓存存服务器原样 JSON，键 = 请求路径；最近最少用的先丢，最多 SWR_MAX 条（= App SwrCache.max）。只在内存（刷新网页即冷启动）。
//  4. 退出登录 / 登录过期 / 重新登录 → swrClear() 整个清空（换人看不到上一个人的数据），清空前发出的请求回来也不再写入。
// React 读法在 hooks/useSwr.ts；本文件是纯逻辑、不依赖 DOM 和其他模块（tests/swr.test.ts 直接用 node 跑）。
// 参考：Vercel SWR（MIT）的公开文档（stale-while-revalidate、请求去重、mutate），只学做法，没有移植代码。

export const SWR_MAX = 64;

const store = new Map<string, unknown>(); // Map 按插入顺序：读到就挪到最后 = LRU
const listeners = new Map<string, Set<() => void>>();
const inflight = new Map<string, Promise<unknown>>();
let generation = 0;

const notify = (key: string) => listeners.get(key)?.forEach((l) => l());

/** 两份 JSON 是否相同（相同就不发新状态：不白白重建、不重播入场动画）。 */
export function sameJson(a: unknown, b: unknown): boolean {
  if (Object.is(a, b)) return true;
  try { return JSON.stringify(a) === JSON.stringify(b); } catch { return false; }
}

export const swrCache = {
  has: (key: string) => store.has(key),
  /** 只看不挪（给 useSyncExternalStore 的快照用：必须纯）。 */
  peek: <T>(key: string) => store.get(key) as T | undefined,
  /** 读并标记为“最近用过”。 */
  read<T>(key: string): T | undefined {
    if (!store.has(key)) return undefined;
    const v = store.get(key);
    store.delete(key);
    store.set(key, v);
    return v as T;
  },
  size: () => store.size,
  keys: () => [...store.keys()],
};

/** 写入一条并通知订阅者；和现有值 JSON 相同则什么都不做（返回 false）。 */
export function swrWrite(key: string, value: unknown): boolean {
  if (store.has(key) && sameJson(store.get(key), value)) {
    swrCache.read(key);
    return false;
  }
  store.delete(key);
  store.set(key, value);
  while (store.size > SWR_MAX) {
    const oldest = store.keys().next().value as string;
    store.delete(oldest); // 不通知：还挂着的组件手里那份照旧显示，下次重取再写回来（挂着的键刚被读过，几乎不会被挤掉）
  }
  notify(key);
  return true;
}

/** 增删改：给新值，或给“旧值 → 新值”。没有旧值时 updater 拿到 undefined。 */
export function swrMutate<T>(key: string, next: T | ((old: T | undefined) => T)): void {
  const v = typeof next === "function" ? (next as (old: T | undefined) => T)(store.get(key) as T | undefined) : next;
  swrWrite(key, v);
}

/** 只在已有缓存时改（比如在详情页改了一条，顺手把列表里那条也改掉；列表没缓存就不凭空造一份）。 */
export function swrPatch<T>(key: string, update: (old: T) => T): void {
  if (store.has(key)) swrWrite(key, update(store.get(key) as T));
}

export function swrRemove(key: string): void {
  if (store.delete(key)) notify(key);
}

/** 取一次并写缓存。同一把键同时只发一个请求（几个组件一起挂载只问一次）。失败照常抛给调用方。 */
export function swrFetch<T>(key: string, fetcher: () => Promise<T>): Promise<T> {
  const running = inflight.get(key);
  if (running) return running as Promise<T>;
  const gen = generation;
  const p = fetcher().then(
    (v) => {
      if (inflight.get(key) === p) inflight.delete(key);
      if (gen === generation) swrWrite(key, v);
      return v;
    },
    (e) => {
      if (inflight.get(key) === p) inflight.delete(key);
      throw e;
    },
  );
  inflight.set(key, p);
  return p;
}

export function swrSubscribe(key: string, fn: () => void): () => void {
  let set = listeners.get(key);
  if (!set) listeners.set(key, (set = new Set()));
  set.add(fn);
  return () => {
    set!.delete(fn);
    if (set!.size === 0) listeners.delete(key);
  };
}

/** 退出登录 / 登录过期 / 换服务器：全部清空，在途请求作废。 */
export function swrClear(): void {
  generation++;
  inflight.clear();
  const keys = [...store.keys()];
  store.clear();
  keys.forEach(notify);
}
