// v2.92 §P 个人资料（= App core/profile.dart）：称呼、给助手取的名字、头像、首次问候。GET/PATCH /api/profile，规则在后端 app/identity.py。
// 取代 GET /api/auth/me（已删）：“我的”页页头、顶栏头像都读这一个 store；改了立刻通知所有订阅者（顶栏首字母跟着变）。
import { useEffect, useSyncExternalStore } from "react";
import { http } from "./api";

export type Profile = {
  username: string;
  display_name: string | null;   // 用户希望被怎么称呼；null = 没说，界面用登录名
  assistant_name: string | null; // 给助手取的名字；null = 叫 assistant_default
  assistant_default: string;
  avatar: string | null;         // /api/profile/avatar/<版本>；null = 纯色圆 + 首字母
  greet: boolean;                // 还没首次问候
};

let current: Profile | null = null;
let loading: Promise<void> | null = null;
const listeners = new Set<() => void>();
const emit = () => listeners.forEach((l) => l());

function take(p: Profile): Profile { current = p; emit(); return p; }

/** 拉一次（同一时刻只发一个请求）；失败（老服务器、断网）保持 null，界面退回“我的”/“我”。 */
export function loadProfile(): Promise<void> {
  return (loading ??= http.get<Profile>("/api/profile").then(take, () => undefined).then(() => { loading = null; }));
}

export function useProfile(): Profile | null {
  const p = useSyncExternalStore((l) => { listeners.add(l); return () => listeners.delete(l); }, () => current);
  useEffect(() => { if (!current) void loadProfile(); }, []);
  return p;
}

/** 页头、头像首字母用的名字：称呼优先，没有用登录名。 */
export const profileName = (p: Profile) => p.display_name?.trim() || p.username;

/** 首字母：名字第一个字（英文大写）；没有名字 → “我”（= App Profile.initial）。 */
export function profileInitial(p: Profile | null): string {
  const n = p ? profileName(p).trim() : "";
  return n ? [...n][0].toUpperCase() : "我";
}

/** 只送改了的字段（空串 = 清除）。错误（如太长）原样抛给调用方显示。 */
export const renameProfile = (fields: Partial<Pick<Profile, "display_name" | "assistant_name">>) =>
  http.patch<Profile>("/api/profile", fields).then(take);
export const uploadAvatar = (f: File) => http.upload<Profile>("/api/profile/avatar", f).then(take);
export const clearAvatar = () => http.del("/api/profile/avatar").then((p) => take(p as Profile));

/** 主聊天空白时调一次：返回问候对话 id（问候过 → null）。先在本地标成已问候，免得重复调。 */
export async function greetOnce(): Promise<string | null> {
  if (!current?.greet) return null;
  take({ ...current, greet: false });
  return http.post<{ conversation_id: string | null }>("/api/profile/greet", {}).then((r) => r.conversation_id, () => null);
}

/** 退出登录时清掉，换账号后重新拉。 */
export function resetProfile() { current = null; emit(); }
