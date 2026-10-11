// 本机外观偏好（设计 v2）：头像色 + 减少透明度。只存 localStorage，和浅/深色一样“按设备”，与 App theme/look.dart 同义。
// 生效方式：头像色写到 <html> 的 --avatar / --on-avatar；减少透明度写 <html data-solid>，tokens.css 据此把玻璃换成实色。
// index.html 首帧脚本做同样的事（键名必须一致），避免先透明后实色的闪烁。
import { useSyncExternalStore } from "react";

/** 4 个预设色，和 App AvatarColors.presets 同值；色轮只选色相，饱和度/明度固定（S 0.62 / V 0.86），选出来都好看、字看得清。 */
export const AVATAR_PRESETS = ["#8a7cc0", "#0e9c9c", "#4d8bf5", "#7d8088"];
const WHEEL_S = 0.62, WHEEL_V = 0.86;
const K_AVATAR = "look.avatar", K_SOLID = "look.solid";

/** avatar = null：默认中性底（tokens.css --avatar，随浅/深色变），和 App Look.avatar == null 同义。 */
export type Look = { avatar: string | null; solid: boolean };
const listeners = new Set<() => void>();
let cached: Look | null = null;

function read(): Look {
  const a = localStorage.getItem(K_AVATAR);
  return { avatar: a && /^#[0-9a-f]{6}$/i.test(a) ? a.toLowerCase() : null, solid: localStorage.getItem(K_SOLID) === "1" };
}

export function getLook(): Look { return (cached ??= read()); }

/** 色相（0–360，0° 在色轮正上方 = 红）→ 固定 S/V 的颜色。 */
export function hueColor(h: number): string {
  const c = WHEEL_V * WHEEL_S, x = c * (1 - Math.abs(((h / 60) % 2) - 1)), m = WHEEL_V - c;
  const [r, g, b] = h < 60 ? [c, x, 0] : h < 120 ? [x, c, 0] : h < 180 ? [0, c, x] : h < 240 ? [0, x, c] : h < 300 ? [x, 0, c] : [c, 0, x];
  return "#" + [r, g, b].map((v) => Math.round((v + m) * 255).toString(16).padStart(2, "0")).join("");
}

/** 颜色 → 色相（给色轮放指针）。灰色返回 null。 */
export function colorHue(hex: string): number | null {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255);
  const max = Math.max(r, g, b), d = max - Math.min(r, g, b);
  if (d < 0.05) return null;
  const h = max === r ? ((g - b) / d) % 6 : max === g ? (b - r) / d + 2 : (r - g) / d + 4;
  return (h * 60 + 360) % 360;
}

/** 头像上的字用白还是深色：亮度 > 0.45 用深色（同 App AvatarColors.inkOn）。 */
export function inkOn(hex: string): string {
  const lin = (v: number) => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4);
  const [r, g, b] = [1, 3, 5].map((i) => lin(parseInt(hex.slice(i, i + 2), 16) / 255));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b > 0.45 ? "#1c1b1a" : "#ffffff";
}

function apply() {
  const { avatar, solid } = getLook();
  const root = document.documentElement;
  if (avatar) {
    root.style.setProperty("--avatar", avatar);
    root.style.setProperty("--on-avatar", inkOn(avatar));
  } else {
    root.style.removeProperty("--avatar");
    root.style.removeProperty("--on-avatar");
  }
  if (solid) root.dataset.solid = ""; else delete root.dataset.solid;
}

function set(patch: Partial<Look>) {
  const next = { ...getLook(), ...patch };
  if (next.avatar) localStorage.setItem(K_AVATAR, next.avatar); else localStorage.removeItem(K_AVATAR);
  if (next.solid) localStorage.setItem(K_SOLID, "1"); else localStorage.removeItem(K_SOLID);
  cached = next;
  apply();
  listeners.forEach((l) => l());
}
export const setAvatarColor = (avatar: string | null) => set({ avatar });
export const setSolid = (solid: boolean) => set({ solid });

export function initLook() { apply(); }

export function useLook(): Look {
  return useSyncExternalStore((l) => { listeners.add(l); return () => listeners.delete(l); }, getLook);
}
