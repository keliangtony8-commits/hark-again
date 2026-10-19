/** 底部提示的状态（网页唯一入口，= App ui/kit.dart showToast；渲染在 ui/toast.tsx ToastHost）。
 *  照 Hark（2026-10-19 用户真机：提示很久不消失）：
 *  - 新替旧：再来一条立刻换掉当前的，不排队；
 *  - 定时消失：短提示 TOAST_MS，带“撤销”等按钮的 TOAST_ACTION_MS，也一定会走；
 *  - 点一下 / 往下滑关掉（ToastHost 调 dismissToast）。
 *  以前网页是各页自己的 .notice / .share-note 状态条，点了才消失，现在统一走这里。 */

export const TOAST_MS = 2000;        // = App Timing.toast
export const TOAST_ACTION_MS = 4000; // = App Timing.toastAction
export const TOAST_EXIT_MS = 240;    // 退场淡出（= --dur）

export type Toast = { id: number; text: string; action?: string; onAction?: () => void; leaving: boolean };

let current: Toast | null = null;
let seq = 0;
let hold: ReturnType<typeof setTimeout> | undefined;
let exit: ReturnType<typeof setTimeout> | undefined;
const listeners = new Set<() => void>();
const emit = () => listeners.forEach((l) => l());

export const toastSubscribe = (l: () => void) => { listeners.add(l); return () => { listeners.delete(l); }; };
export const toastCurrent = () => current;

function clearTimers() {
  clearTimeout(hold);
  clearTimeout(exit);
  hold = exit = undefined;
}

/** 出一条提示；给了 action 就带一个按钮（点了调 onAction 并收起）。 */
export function toast(text: string, opts: { action?: string; onAction?: () => void } = {}) {
  clearTimers();
  current = { id: ++seq, text, action: opts.action, onAction: opts.onAction, leaving: false };
  emit();
  hold = setTimeout(dismissToast, opts.action ? TOAST_ACTION_MS : TOAST_MS);
}

/** 收起当前提示：先淡出再移除；已经在收就不重来。 */
export function dismissToast() {
  if (!current || current.leaving) return;
  clearTimers();
  current = { ...current, leaving: true };
  emit();
  exit = setTimeout(() => { current = null; exit = undefined; emit(); }, TOAST_EXIT_MS);
}

/** 测试用：清空状态和计时器。 */
export function toastReset() {
  clearTimers();
  current = null;
  emit();
}
