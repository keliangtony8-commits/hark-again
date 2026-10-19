import { useRef, useSyncExternalStore } from "react";
import { dismissToast, toastCurrent, toastSubscribe } from "../lib/toast";

/** 底部提示的渲染（App 根上挂一个，= App SnackBar 浮条）；状态与规则在 lib/toast.ts。
 *  点一下关掉；往下滑超过 SWIPE 关掉；按钮（撤销等）点了先回调再收起。 */
const SWIPE = 24;

export function ToastHost() {
  const t = useSyncExternalStore(toastSubscribe, toastCurrent);
  const startY = useRef<number | null>(null);
  if (!t) return null;
  return (
    <div className="toast-wrap">
      <div
        key={t.id}
        className={`toast${t.leaving ? " out" : ""}`}
        role="status"
        aria-live="polite"
        onClick={dismissToast}
        onPointerDown={(e) => { startY.current = e.clientY; }}
        onPointerUp={(e) => { if (startY.current !== null && e.clientY - startY.current > SWIPE) dismissToast(); startY.current = null; }}
      >
        <span className="toast-text">{t.text}</span>
        {t.action && (
          <button className="toast-action" onClick={(e) => { e.stopPropagation(); t.onAction?.(); dismissToast(); }}>{t.action}</button>
        )}
      </div>
    </div>
  );
}
