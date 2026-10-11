import { useEffect, useRef, useSyncExternalStore } from "react";

/** 居中玻璃对话框：网页端唯一的“确认 / 提示”入口，和 App ui/sheets.dart 的 confirmDanger / showAppDialog 同义。
 *  - 不用 window.confirm / alert（浏览器原生框丑、阻塞线程、安卓 WebView 里样式不可控）：
 *    scripts/check-arch.mjs 守着，src 里出现就 build 失败。
 *  - 命令式调用（await confirmDialog(...)），这样按钮回调里一行就能用，不用每个页面自己管 open 状态；
 *    App 根上挂一个 <DialogHost/> 负责渲染，同一时刻只有一个对话框（新的会顶掉旧的并按“取消”结算旧的）。 */

export type ConfirmOptions = {
  title: string;
  text?: string;
  /** 确认键的字，默认“删除”。 */
  action?: string;
  /** 确认键用危险色（删除、断开、放弃改动）；false = 主色墨黑。默认 true。 */
  danger?: boolean;
};

type Pending = { kind: "confirm" | "notice"; opts: ConfirmOptions; resolve: (ok: boolean) => void };

let current: Pending | null = null;
const listeners = new Set<() => void>();
const emit = () => listeners.forEach((l) => l());
const subscribe = (l: () => void) => { listeners.add(l); return () => { listeners.delete(l); }; };

function open(kind: Pending["kind"], opts: ConfirmOptions): Promise<boolean> {
  current?.resolve(false);
  return new Promise((resolve) => { current = { kind, opts, resolve }; emit(); });
}

function settle(ok: boolean) {
  const p = current;
  current = null;
  emit();
  p?.resolve(ok);
}

/** 两颗等宽胶囊（取消 / 动作）的确认框；点遮罩、Esc = 取消。 */
export const confirmDialog = (opts: ConfirmOptions) => open("confirm", { danger: true, action: "删除", ...opts });

/** 一句话提示（出错、做不到）：只有一颗“知道了”。 */
export const noticeDialog = (title: string, text?: string) => open("notice", { title, text, action: "知道了", danger: false }).then(() => undefined);

export function DialogHost() {
  const p = useSyncExternalStore(subscribe, () => current);
  const okRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (!p) return;
    okRef.current?.focus();
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") settle(false); };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [p]);
  if (!p) return null;
  const { title, text, action, danger } = p.opts;
  return (
    <div className="dialog-scrim" onClick={() => settle(false)}>
      <div className="dialog" role="alertdialog" aria-modal="true" aria-label={title} onClick={(e) => e.stopPropagation()}>
        <h2>{title}</h2>
        {text && <p>{text}</p>}
        <div className="dialog-actions">
          {p.kind === "confirm" && <button className="btn btn-soft" onClick={() => settle(false)}>取消</button>}
          <button ref={okRef} className={`btn ${danger ? "btn-danger-fill" : "btn-primary"}`} onClick={() => settle(true)}>{action}</button>
        </div>
      </div>
    </div>
  );
}
