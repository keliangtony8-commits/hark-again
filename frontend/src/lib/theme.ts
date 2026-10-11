// 外观偏好：跟随系统 / 浅色 / 深色。只存本机 localStorage，与 App 的 theme/appearance.dart 同义。
// 生效方式：给 <html> 写 data-theme="light|dark"，tokens.css 只认这个属性；
// index.html 里的内联脚本在首帧前做同样的事，避免先亮后暗的闪烁（键名必须和这里一致）。
import { useSyncExternalStore } from "react";

export type Appearance = "system" | "light" | "dark";
export const APPEARANCES: { value: Appearance; label: string }[] = [
  { value: "system", label: "跟随系统" },
  { value: "light", label: "浅色" },
  { value: "dark", label: "深色" },
];

const KEY = "appearance";
const media = window.matchMedia("(prefers-color-scheme: dark)");
const listeners = new Set<() => void>();

export function getAppearance(): Appearance {
  const v = localStorage.getItem(KEY);
  return v === "light" || v === "dark" ? v : "system";
}

function apply(animate: boolean) {
  const a = getAppearance();
  const resolved = a === "system" ? (media.matches ? "dark" : "light") : a;
  const root = document.documentElement;
  if (root.dataset.theme === resolved) return;
  if (animate) {
    // 切换期间临时给所有元素加颜色过渡（base.css 的 .theme-switching），结束即撤，不拖累平时的动效
    root.classList.add("theme-switching");
    window.setTimeout(() => root.classList.remove("theme-switching"), 400);
  }
  root.dataset.theme = resolved;
  const bg = getComputedStyle(root).getPropertyValue("--bg").trim();
  document.querySelector('meta[name="theme-color"]')?.setAttribute("content", bg);
}

export function setAppearance(a: Appearance) {
  if (a === "system") localStorage.removeItem(KEY);
  else localStorage.setItem(KEY, a);
  apply(true);
  listeners.forEach((l) => l());
}

/** 启动时调一次：校正首帧结果，并在“跟随系统”时监听系统切换。 */
export function initAppearance() {
  apply(false);
  media.addEventListener("change", () => apply(true));
}

export function useAppearance(): Appearance {
  return useSyncExternalStore((l) => { listeners.add(l); return () => listeners.delete(l); }, getAppearance);
}
