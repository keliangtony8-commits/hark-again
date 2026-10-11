import { useCallback, useEffect, useState } from "react";
import { http } from "../lib/api";

/** 列表型资源的通用 hook：加载、增、改、删、动作，全部页面共用。 */
export function useResource<T extends { id: string }>(path: string) {
  const [items, setItems] = useState<T[]>([]);
  const [loading, setLoading] = useState(true);

  const reload = useCallback(async () => {
    setLoading(true);
    try { setItems(await http.get<T[]>(path)); } finally { setLoading(false); }
  }, [path]);

  useEffect(() => { reload(); }, [reload]);

  const base = path.split("?")[0];
  const create = async (body: Partial<T>) => { const x = await http.post<T>(base, body); setItems((s) => [x, ...s]); return x; };
  const update = async (id: string, body: Partial<T>) => {
    const x = await http.patch<T>(`${base}/${id}`, body);
    setItems((s) => s.map((i) => (i.id === id ? x : i)));
    return x;
  };
  /** 资源上的动作（POST base/id/action），服务器返回新条目就地替换。 */
  const act = async (id: string, action: string) => {
    const x = await http.post<T>(`${base}/${id}/${action}`, {});
    setItems((s) => s.map((i) => (i.id === id ? x : i)));
    return x;
  };
  const remove = async (id: string) => { await http.del(`${base}/${id}`); setItems((s) => s.filter((i) => i.id !== id)); };

  return { items, loading, reload, create, update, act, remove };
}
