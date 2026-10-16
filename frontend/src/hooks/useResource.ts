import { http } from "../lib/api";
import { useSwr } from "./useSwr";

const EMPTY: never[] = [];

/** 列表型资源的通用 hook：加载、增、改、删、动作，全部页面共用。读法走 useSwr（再进页面先显示上次的列表，后台对齐）；
 *  增删改把服务器返回写回同一份缓存，别的页面用同一把 key 的列表跟着变。 */
export function useResource<T extends { id: string }>(path: string) {
  const { data, loading, reload, mutate } = useSwr<T[]>(path);
  const items = data ?? (EMPTY as T[]);

  const base = path.split("?")[0];
  const create = async (body: Partial<T>) => { const x = await http.post<T>(base, body); mutate((s) => [x, ...(s ?? [])]); return x; };
  const update = async (id: string, body: Partial<T>) => {
    const x = await http.patch<T>(`${base}/${id}`, body);
    mutate((s) => (s ?? []).map((i) => (i.id === id ? x : i)));
    return x;
  };
  /** 资源上的动作（POST base/id/action），服务器返回新条目就地替换。 */
  const act = async (id: string, action: string) => {
    const x = await http.post<T>(`${base}/${id}/${action}`, {});
    mutate((s) => (s ?? []).map((i) => (i.id === id ? x : i)));
    return x;
  };
  const remove = async (id: string) => { await http.del(`${base}/${id}`); mutate((s) => (s ?? []).filter((i) => i.id !== id)); };

  return { items, loading, reload, create, update, act, remove };
}
