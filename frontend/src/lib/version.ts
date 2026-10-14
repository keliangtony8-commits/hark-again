// 版本（v2.86，= App models/version.dart）：本机版本来自 src/brand.ts（brand/sync.py 由 VERSION 生成），服务器版本来自 GET /api/version。
import { appVersion } from "../brand";

export type ServerVersion = { version: string; minClient: string };

export function parseVersion(s: string): [number, number, number] | null {
  const m = /^(\d+)\.(\d+)\.(\d+)$/.exec(s.trim());
  return m ? [Number(m[1]), Number(m[2]), Number(m[3])] : null;
}

/** a < b（大版本.功能轮.修复）；解析不了的当作不小于（不误报“请更新”）。 */
export function versionBelow(a: string, b: string): boolean {
  const x = parseVersion(a), y = parseVersion(b);
  if (!x || !y) return false;
  for (let i = 0; i < 3; i++) if (x[i] !== y[i]) return x[i] < y[i];
  return false;
}

/** 老服务器没有这个接口 / 字段不对 → null。 */
export function serverVersionFrom(j: unknown): ServerVersion | null {
  if (!j || typeof j !== "object") return null;
  const { version, min_client } = j as { version?: unknown; min_client?: unknown };
  if (typeof version !== "string" || !parseVersion(version)) return null;
  return { version, minClient: typeof min_client === "string" && parseVersion(min_client) ? min_client : "0.0.0" };
}

export const clientOutdated = (s: ServerVersion | null, client = appVersion) => !!s && versionBelow(client, s.minClient);
export const clientVersionLabel = (s: ServerVersion | null, client = appVersion) => (clientOutdated(s, client) ? `${client} · 请更新` : client);
