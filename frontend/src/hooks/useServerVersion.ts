import { useEffect, useState } from "react";
import { http } from "../lib/api";
import { serverVersionFrom, type ServerVersion } from "../lib/version";

/** GET /api/version（公开接口，= App serverVersionProvider）：关于页两段版本、“我的 → 关于”行尾“请更新”。取不到 = null。 */
export function useServerVersion(): ServerVersion | null {
  const [v, setV] = useState<ServerVersion | null>(null);
  useEffect(() => {
    let live = true;
    http.get<unknown>("/api/version").then((j) => { if (live) setV(serverVersionFrom(j)); }).catch(() => {});
    return () => { live = false; };
  }, []);
  return v;
}
