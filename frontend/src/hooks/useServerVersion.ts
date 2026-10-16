import { useMemo } from "react";
import { serverVersionFrom, type ServerVersion } from "../lib/version";
import { useSwr } from "./useSwr";

/** GET /api/version（公开接口，= App serverVersionProvider）：关于页两段版本、“我的 → 关于”行尾“请更新”。取不到 = null。 */
export function useServerVersion(): ServerVersion | null {
  const { data } = useSwr<unknown>("/api/version");
  return useMemo(() => (data === undefined ? null : serverVersionFrom(data)), [data]);
}
