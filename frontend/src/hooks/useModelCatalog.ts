import { useEffect, useState } from "react";
import { cachedModels, fetchModels, type ModelCatalog } from "../lib/models";

/** 可选模型列表：缓存先行，后台刷新。不足两项时界面不给切换。 */
export function useModelCatalog(): ModelCatalog | null {
  const [cat, setCat] = useState<ModelCatalog | null>(cachedModels);
  useEffect(() => {
    let alive = true;
    fetchModels().then((c) => alive && setCat(c)).catch(() => {});
    return () => { alive = false; };
  }, []);
  return cat;
}
