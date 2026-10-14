// 原地聚焦菜单（home-redesign §J，= App ui/focus_menu.dart）：全站唯一的“长按 / 右键 / ⋯”消息菜单，取代 v2.84 的 kit Menu 小下拉。
// 整屏重度模糊变暗（.focus-scrim）；被按的那条留在原位、保持清晰（克隆它的 DOM 放回原处，轻微放大 2% 再落回）；
// 紧贴它下方（放不下就上方，再放不下就贴窗口底）、同侧对齐弹出菜单卡；点空白 / Esc / 滚动 / 改窗口大小 收起。
// 超过 FOCUS_ROWS 行时前几行 + “更多”原地展开。动效只用 base.css 的 keyframes（减弱动效时全局关掉）。
import { useCallback, useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import type { MenuItem } from "./kit";
import { IconMore } from "./icons";

const FOCUS_ROWS = 5;   // = App Layout.focusMenuRows
const ROW = 48;         // 一行高（= A11y.minTap）
const PAD = 8;          // 菜单卡上下内边距
const EDGE = 16;        // 离窗口边

type Props = { anchor: HTMLElement; items: MenuItem[]; alignEnd?: boolean; label: string; onClose: () => void };

export function FocusMenu({ anchor, items, alignEnd = false, label, onClose }: Props) {
  const [more, setMore] = useState(false);
  const lift = useRef<HTMLDivElement>(null);
  const menu = useRef<HTMLDivElement>(null);
  const [rect] = useState(() => anchor.getBoundingClientRect());
  const shown = more || items.length <= FOCUS_ROWS ? items : items.slice(0, FOCUS_ROWS - 1);
  const hasMore = !more && items.length > FOCUS_ROWS;

  // 被按的那条：克隆一份放回原位（只是样子，点不到）
  useLayoutEffect(() => {
    const box = lift.current;
    if (!box) return;
    const copy = anchor.cloneNode(true) as HTMLElement;
    copy.removeAttribute("id");
    copy.style.margin = "0";
    copy.style.width = `${rect.width}px`;
    box.replaceChildren(copy);
  }, [anchor, rect.width]);

  useEffect(() => {
    menu.current?.querySelector<HTMLButtonElement>("button")?.focus({ preventScroll: true });
    const key = (e: KeyboardEvent) => { if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); onClose(); } };
    const away = () => onClose();
    document.addEventListener("keydown", key, true);
    window.addEventListener("resize", away);
    document.addEventListener("scroll", away, true);
    return () => { document.removeEventListener("keydown", key, true); window.removeEventListener("resize", away); document.removeEventListener("scroll", away, true); };
  }, [onClose]);

  const rows = shown.length + (hasMore ? 1 : 0);
  const h = rows * ROW + PAD * 2;
  const w = Math.min(232, window.innerWidth - EDGE * 2);
  const below = rect.bottom + 8 + h <= window.innerHeight - EDGE;
  const above = !below && rect.top - 8 - h >= EDGE;
  const top = below ? rect.bottom + 8 : above ? rect.top - 8 - h : window.innerHeight - EDGE - h;
  const left = Math.min(Math.max(EDGE / 2, alignEnd ? rect.right - w : rect.left), window.innerWidth - EDGE / 2 - w);
  const origin = `${below ? "top" : "bottom"} ${alignEnd ? "right" : "left"}`;

  return createPortal(
    <div className="focus-layer" onClick={(e) => e.stopPropagation()} onContextMenu={(e) => { e.preventDefault(); onClose(); }}>
      <div className="focus-scrim" onClick={onClose} aria-hidden />
      <div className="focus-lift" ref={lift} aria-hidden style={{ left: rect.left, top: rect.top, width: rect.width, height: rect.height }} />
      <div className="focus-menu" role="menu" aria-label={label} ref={menu} style={{ left, top, width: w, transformOrigin: origin }}>
        {shown.map((it) => (
          <button key={it.label} role="menuitem" className={`focus-item ${it.danger ? "danger" : ""}`} onClick={() => { onClose(); it.onSelect(); }}>
            {it.icon}<span>{it.label}</span>
          </button>
        ))}
        {hasMore && (
          <button role="menuitem" className="focus-item" onClick={() => setMore(true)}><IconMore /><span>更多</span></button>
        )}
      </div>
    </div>,
    document.body,
  );
}

/** 一条消息的聚焦菜单：open(元素) 从“⋯”或右键打开；node 放进组件树里。 */
export function useFocusMenu(items: () => MenuItem[], opts: { alignEnd?: boolean; label: string }) {
  const [anchor, setAnchor] = useState<HTMLElement | null>(null);
  const close = useCallback(() => setAnchor(null), []);
  const open = useCallback((el: HTMLElement | null) => { if (el && items().length) setAnchor(el); }, [items]);
  const node: ReactNode = anchor ? <FocusMenu anchor={anchor} items={items()} alignEnd={opts.alignEnd} label={opts.label} onClose={close} /> : null;
  return { open, node, isOpen: !!anchor };
}
