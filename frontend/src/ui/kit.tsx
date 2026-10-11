import { useEffect, useLayoutEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import { IconBack, IconClose, IconSearch } from "./icons";
import "./ui.css";

/** 子页面的浮动玻璃标题栏（返回 + 标题 + 右侧操作），和一级页面的顶栏同位置。 */
export function PageHeader({ title, back, action }: { title: string; back?: boolean; action?: ReactNode }) {
  const nav = useNavigate();
  return (
    <header className="page-head">
      {back && <button className="icon-btn" onClick={() => nav(-1)} aria-label="返回"><IconBack /></button>}
      <h1>{title}</h1>
      {action ?? (back ? <span className="spacer" /> : null)}
    </header>
  );
}

/** 底部浮层：贴着父容器底部（父容器要 position: relative），量自己的实际高度报给 onHeight，
 *  让下面的滚动内容留出同样的空（输入胶囊会随附件/编辑条/多行文字长高）。和 App ui/kit.dart FloatingFooter 同义。 */
export function FloatingFooter({ children, onHeight }: { children: ReactNode; onHeight: (h: number) => void }) {
  const ref = useRef<HTMLDivElement>(null);
  const cb = useRef(onHeight);
  cb.current = onHeight;
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const report = () => cb.current(el.offsetHeight);
    report();
    const ro = new ResizeObserver(report);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return <div ref={ref} className="floating-footer">{children}</div>;
}

/** 页面骨架：可滚动内容 + 可选的子页面标题栏 + 可选的底部浮层（一级页面的输入胶囊）。 */
export function Page({ children, header, footer }: { children: ReactNode; header?: ReactNode; footer?: ReactNode }) {
  const [h, setH] = useState(0);
  const style = footer ? ({ ["--footer-h" as string]: `${h}px` } as CSSProperties) : undefined;
  return (
    <>
      <div className={`page ${footer ? "has-composer" : ""}`} style={style}>{header}<div className="page-inner">{children}</div></div>
      {footer && <FloatingFooter onHeight={setH}>{footer}</FloatingFooter>}
    </>
  );
}

/** 错峰入场的序号（配 .enter：延迟 = --stagger × --i，封顶 10，= App Motion.stagger）。 */
export const stagger = (i: number) => ({ "--i": Math.min(Math.max(i, 0), 10) }) as CSSProperties;

/** 区块。enter = 错峰入场序号（不给就不做入场动画）。 */
export function Section({ title, action, children, enter }: { title?: string; action?: ReactNode; children: ReactNode; enter?: number }) {
  return (
    <section className={enter === undefined ? "section" : "section enter"} style={enter === undefined ? undefined : stagger(enter)}>
      {title && <div className="section-title"><span>{title}</span>{action}</div>}
      {children}
    </section>
  );
}

/** 子页页头（= App PageIntro）：一行小标签摘要（变化时重新入场）+ 一句说明。loading 时留位不闪。 */
export function PageIntro({ summary, line, loading }: { summary: string; line: string; loading?: boolean }) {
  return (
    <div className="page-intro enter">
      <span key={loading ? "" : summary} className="page-hero-label enter">{loading ? "" : summary}</span>
      <p key={loading ? "" : line} className="desc enter">{loading ? "\u00a0" : line}</p>
    </div>
  );
}

/** 起步卡（= App StarterCard）：列表为空时代替空状态——标题 + 引导 + 一排起步按钮。 */
export function StarterCard({ title, text, children }: { title: string; text: string; children: ReactNode }) {
  return (
    <div className="list starters enter">
      <div className="row-title">{title}</div>
      <p className="row-sub">{text}</p>
      <div className="starter-list">{children}</div>
    </div>
  );
}

export function Hint({ icon, title, text, action }: { icon: ReactNode; title: string; text: string; action?: ReactNode }) {
  return (
    <div className="hint">
      <div className="hint-icon">{icon}</div>
      <h3>{title}</h3>
      <p>{text}</p>
      {action}
    </div>
  );
}

export function Skeleton({ rows = 3 }: { rows?: number }) {
  return <>{Array.from({ length: rows }, (_, i) => <div key={i} className="skeleton" />)}</>;
}

/** 开关：没有可见文字，所以 label 必填（读屏念的就是它）。 */
export function Toggle({ on, onChange, label }: { on: boolean; onChange: (v: boolean) => void; label: string }) {
  return <button role="switch" aria-checked={on} aria-label={label} className={`toggle ${on ? "on" : ""}`} onClick={() => onChange(!on)} />;
}

/** 分段选择：选中块是一块滑动的底（--i 决定位置），三端同一手感。 */
export function Segmented<T extends string>({ value, options, onChange, label }: { value: T; options: { value: T; label: string }[]; onChange: (v: T) => void; label?: string }) {
  const i = Math.max(0, options.findIndex((o) => o.value === value));
  return (
    <div className="segmented" role="radiogroup" aria-label={label} style={{ ["--n" as string]: options.length, ["--i" as string]: i }}>
      <span className="segmented-thumb" aria-hidden />
      {options.map((o) => (
        <button key={o.value} role="radio" aria-checked={o.value === value} className={o.value === value ? "on" : ""} onClick={() => onChange(o.value)}>{o.label}</button>
      ))}
    </div>
  );
}

export function Sheet({ title, onClose, children, actions }: { title: string; onClose: () => void; children: ReactNode; actions?: ReactNode }) {
  return (
    <div className="sheet-scrim" onClick={onClose}>
      <div className="sheet" onClick={(e) => e.stopPropagation()} role="dialog" aria-label={title}>
        <div className="sheet-grip" />
        <h2>{title}</h2>
        {children}
        {actions && <div className="sheet-actions">{actions}</div>}
      </div>
    </div>
  );
}

/** 圆角搜索框（对话历史、记忆页共用）：有字时给清空键，Esc 清空。与 App SearchField 同款。 */
export function SearchField({ value, onChange, placeholder, className = "" }: { value: string; onChange: (v: string) => void; placeholder: string; className?: string }) {
  return (
    <label className={`search-field ${className}`}>
      <IconSearch />
      <input value={value} onChange={(e) => onChange(e.target.value)} placeholder={placeholder} aria-label={placeholder}
        onKeyDown={(e) => e.key === "Escape" && onChange("")} />
      {value && <button className="icon-btn sm" aria-label="清空" onClick={() => onChange("")}><IconClose /></button>}
    </label>
  );
}

/** 把 q 在 text 里的所有出现（不分大小写）标亮。与 App 的 HighlightText 同规则。 */
export function Highlight({ text, q }: { text: string; q: string }) {
  const needle = q.trim().toLowerCase();
  if (!needle) return <>{text}</>;
  const out: ReactNode[] = [];
  const lower = text.toLowerCase();
  let at = 0;
  for (let i = lower.indexOf(needle); i >= 0; i = lower.indexOf(needle, at)) {
    if (i > at) out.push(text.slice(at, i));
    out.push(<mark key={i} className="hl">{text.slice(i, i + needle.length)}</mark>);
    at = i + needle.length;
  }
  out.push(text.slice(at));
  return <>{out}</>;
}

export type MenuItem = { label: string; icon?: ReactNode; danger?: boolean; onSelect: () => void };

/** 小弹出菜单：点触发按钮开，点外面 / Esc / 选中后关。 */
export function Menu({ trigger, items, label = "更多" }: { trigger: ReactNode; items: MenuItem[]; label?: string }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const close = (e: Event) => {
      if (e instanceof KeyboardEvent ? e.key === "Escape" : !ref.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", close);
    document.addEventListener("keydown", close);
    return () => { document.removeEventListener("pointerdown", close); document.removeEventListener("keydown", close); };
  }, [open]);
  return (
    <div className={`menu ${open ? "open" : ""}`} ref={ref} onClick={(e) => e.stopPropagation()}>
      <button className="icon-btn sm menu-trigger" aria-label={label} aria-expanded={open} onClick={() => setOpen((o) => !o)}>{trigger}</button>
      {open && (
        <div className="menu-pop" role="menu">
          {items.map((it) => (
            <button key={it.label} role="menuitem" className={`menu-item ${it.danger ? "danger" : ""}`}
              onClick={() => { setOpen(false); it.onSelect(); }}>{it.icon}{it.label}</button>
          ))}
        </div>
      )}
    </div>
  );
}
