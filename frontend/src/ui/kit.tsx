import { useEffect, useLayoutEffect, useRef, useState, type CSSProperties, type ReactNode, type RefObject } from "react";
import { createPortal } from "react-dom";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { IconBack, IconCheck, IconChevron, IconClose, IconSearch } from "./icons";
import { SkyFade } from "./Sky";
import "./ui.css";

/** 子页面标题行（v3.5 照 Hark，= App GlassAppBar）：[圆玻璃返回钮] 居中裸字标题 [操作玻璃胶囊]，和一级页面的顶栏同位置、同高。 */
export function PageHeader({ title, back, action }: { title: string; back?: boolean; action?: ReactNode }) {
  const nav = useNavigate();
  return (
    <header className="page-head">
      {back && <button className="glass-btn glass" onClick={() => nav(-1)} aria-label="返回" title="返回"><IconBack /></button>}
      <h1>{title}</h1>
      {action && <div className="page-head-actions">{action}</div>}
    </header>
  );
}

/** 底部浮层：贴着父容器底部（父容器要 position: relative），量自己的实际高度报给 onHeight，
 *  让下面的滚动内容留出同样的空（输入胶囊会随附件/编辑条/多行文字长高）。和 App ui/kit.dart FloatingFooter 同义。 */
export function FloatingFooter({ children, onHeight }: { children: ReactNode; onHeight: (h: number) => void }) {
  const ref = useRef<HTMLDivElement>(null);
  const [h, setH] = useState(0);
  const cb = useRef(onHeight);
  cb.current = onHeight;
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const report = () => { cb.current(el.offsetHeight); setH(el.offsetHeight); };
    report();
    const ro = new ResizeObserver(report);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  // v3.5 底部渐隐（= App FloatingFooter 的 BackdropFade.bottom）：底条上沿再往上 16px 以上内容全显，到胶囊中线全是壁纸，滚过的内容淡进壁纸不被硬切；
  // 所以滚动内容底部留白要 ≥ --footer-h + 16px（.thread-inner / .page.has-composer 已是）
  return (
    <>
      {h > 0 && <SkyFade kind="footer" height={h + 16} />}
      <div ref={ref} className="floating-footer">{children}</div>
    </>
  );
}

/** 页面骨架：可滚动内容 + 可选的子页面标题栏 + 可选的底部浮层（一级页面的输入胶囊、“我的”页的设置搜索）。所有页同一阅读宽度 --content-w、居中
 *  （v2.94 删掉了宽版 wide：宽屏两栏 / 项目网格都已不在，留着只会让内容贴左、右边空一块）。
 *  v3.0：地址带 ?focus=<id>（“我的”页设置搜索直达，索引 features/me/meIndex.ts）时，等页里 data-spot=<id> 的那一项出现，滚到它并闪一下。 */
export function Page({ children, header, footer, className = "" }: { children: ReactNode; header?: ReactNode; footer?: ReactNode; className?: string }) {
  const [h, setH] = useState(0);
  const box = useRef<HTMLDivElement>(null);
  useSpotlight(box);
  const style = footer ? ({ ["--footer-h" as string]: `${h}px` } as CSSProperties) : undefined;
  return (
    <>
      <div ref={box} className={["page", className, footer ? "has-composer" : ""].filter(Boolean).join(" ")} style={style}>{header}<div className="page-inner">{children}</div></div>
      <SkyFade kind="page" />
      {footer && <FloatingFooter onHeight={setH}>{footer}</FloatingFooter>}
    </>
  );
}

/** 让一个元素闪一下（.flash：底色先停住再淡出，keyframes 在 base.css，时长 --dur-flash）。重复调用会重新闪。
 *  聊天里搜索命中 / 点引用跳到的消息、设置搜索直达的那一项共用。减少动态时不放动画：底色直接出现，到点消失（.flash.hold）。 */
export function flashOnce(el: HTMLElement) {
  el.classList.remove("flash", "hold");
  void el.offsetWidth; // 重新触发动画
  el.classList.add("flash");
  if (matchMedia("(prefers-reduced-motion: reduce)").matches) {
    el.classList.add("hold");
    const ms = parseFloat(getComputedStyle(el).getPropertyValue("--dur-flash")) || 0;
    window.setTimeout(() => el.classList.remove("flash", "hold"), ms);
  } else {
    el.addEventListener("animationend", () => el.classList.remove("flash"), { once: true });
  }
}

/** 等设置项出现最多多久（数据是异步取的：安全页的两步验证、电脑页的各节）。超时就停在页面顶部，不再找。 */
const SPOT_WAIT_MS = 5000;

function useSpotlight(root: RefObject<HTMLElement | null>) {
  const { search, pathname } = useLocation();
  useEffect(() => {
    const id = new URLSearchParams(search).get("focus");
    const node = root.current;
    if (!id || !node) return;
    const reveal = () => {
      const el = node.querySelector<HTMLElement>(`[data-spot="${CSS.escape(id)}"]`);
      // 区块数据异步取（登录设备、电脑页各节）：内容出来前高度为 0，这时滚过去只会闪一条空边 → 等有内容再定位，超时不闪
      if (!el || el.getBoundingClientRect().height < 1) return false;
      const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
      el.scrollIntoView({ block: "center", behavior: reduce ? "auto" : "smooth" });
      flashOnce(el);
      return true;
    };
    if (reveal()) return;
    const mo = new MutationObserver(() => { if (reveal()) stop(); });
    const timer = window.setTimeout(() => stop(), SPOT_WAIT_MS);
    const stop = () => { mo.disconnect(); window.clearTimeout(timer); };
    mo.observe(node, { childList: true, subtree: true });
    return stop;
  }, [search, pathname, root]);
}

/** 可被设置搜索定位的一整块（分区 / 卡片）：只加一个 data-spot 外壳，不改里面的版式。分组里的一行用 ListRow 的 spot。 */
export function Spot({ id, children }: { id: string; children: ReactNode }) {
  return <div className="spot" data-spot={id}>{children}</div>;
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

/** 子页页头（全站唯一，= App PageIntro；v2.97 E1 并入原 .sub-line 手写段落）：一行小标签摘要（变化时重新入场）+ 一句说明。
 *  没有 summary（静态页：关于、偏好、“我的”分组页）时只有那句说明，下面留一个区块间距。loading 时留位不闪。 */
export function PageIntro({ summary, line, loading }: { summary?: string; line: string; loading?: boolean }) {
  if (summary === undefined) return <p className="desc sub-line enter">{line}</p>;
  return (
    <div className="page-intro enter">
      <span key={loading ? "" : summary} className="page-hero-label enter">{loading ? "" : summary}</span>
      <p key={loading ? "" : line} className="desc enter">{loading ? "\u00a0" : line}</p>
    </div>
  );
}

/** 分组列表（全站唯一，= App ListGroup，v2.97 E1）：一张卡里多行 [ListRow]，行间发丝线。enter = 错峰入场序号。 */
export function ListGroup({ children, enter, className = "", label, role }: { children: ReactNode; enter?: number; className?: string; label?: string; role?: string }) {
  return (
    <div className={["list", className, enter === undefined ? "" : "enter"].filter(Boolean).join(" ")} style={enter === undefined ? undefined : stagger(enter)}
      aria-label={label} role={role}>
      {children}
    </div>
  );
}

/** 列表行（全站唯一，= App ListRow，v2.97 E1）：行首图标 + 标题（+ 副标题 / 问题）+ 行尾值 / 控件 / 箭头。
 *  to = 站内链接；onClick = 整行是按钮；都没有 = 静态行。可点的行默认带箭头，trail 给了就用 trail（null = 什么都不放）。
 *  control = 行尾的控件（开关、分段按钮、头像），原样放、不套次要色的 .row-trail。
 *  v2.98：href = 站外链接（新标签页，默认不带箭头）；disabled = 整行按钮禁用；role="group" 时正文 aria-hidden（读屏只念 label）；
 *  iconClass = 行首图标位的额外类（file-ext 扩展名方块）。
 *  v3.5：control 只放可交互的控件（不可点的小字放 trail）。行可点又给了 control = 分体行（= App ListRow onTap + trailing）：
 *  div.row.row-split > 可点主体 .row-main（图标 + 正文 + 值 + trail/箭头，label 落在它上面）+ 控件（按钮不套按钮）。
 *  extra = 正文附加槽：副标题下面、仍在正文里（细条、警示句）。 */
export function ListRow({ icon, iconClass, title, sub, problem, extra, value, trail, control, to, href, onClick, disabled, off, className = "", enter, label, role, spot }: {
  icon?: ReactNode; iconClass?: string; title: ReactNode; sub?: ReactNode; problem?: string; extra?: ReactNode; value?: string; trail?: ReactNode; control?: ReactNode;
  to?: string; href?: string; onClick?: () => void; disabled?: boolean; off?: boolean; className?: string; enter?: number; label?: string; role?: string;
  /** v3.0 设置搜索直达的定位 id（= meIndex.ts 的 focus）：Page 找到 data-spot 后滚到这一行闪一下。 */
  spot?: string;
}) {
  const cls = ["row", className, off ? "row-off" : "", enter === undefined ? "" : "enter"].filter(Boolean).join(" ");
  const style = enter === undefined ? undefined : stagger(enter);
  const tail = trail !== undefined ? trail : (to || onClick) ? <IconChevron /> : null;
  const split = Boolean(control) && Boolean(to || href || onClick);
  const main = (
    <>
      {icon && <span className={iconClass ? `row-icon ${iconClass}` : "row-icon"}>{icon}</span>}
      <div className="row-body" aria-hidden={role === "group" || undefined}>
        <div className="row-title">{title}</div>
        {(sub || problem) && <div className="row-sub">{problem && <span className="row-problem">{problem}</span>}{problem && sub ? " · " : ""}{sub}</div>}
        {extra}
      </div>
      {value && <span className="row-value">{value}</span>}
      {!split && control}
      {tail && <span className="row-trail">{tail}</span>}
    </>
  );
  // 分体行：外层只是容器，链接 / 按钮是里面的主体
  const own = split ? "row-main" : cls;
  const ownStyle = split ? undefined : style;
  const ownSpot = split ? undefined : spot;
  const body = to ? <Link to={to} className={own} style={ownStyle} aria-label={label} data-spot={ownSpot}>{main}</Link>
    : href ? <a href={href} target="_blank" rel="noreferrer" className={own} style={ownStyle} aria-label={label} data-spot={ownSpot}>{main}</a>
    : onClick ? <button type="button" className={own} style={ownStyle} onClick={onClick} disabled={disabled} aria-label={label} data-spot={ownSpot}>{main}</button>
    : null;
  if (split) return <div className={`${cls} row-split`} style={style} data-spot={spot}>{body}{control}</div>;
  return body ?? <div className={cls} style={style} aria-label={label} role={role} data-spot={spot}>{main}</div>;
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
export function Toggle({ on, onChange, label, disabled }: { on: boolean; onChange: (v: boolean) => void; label: string; disabled?: boolean }) {
  return <button type="button" role="switch" aria-checked={on} aria-label={label} disabled={disabled} className={`toggle ${on ? "on" : ""}`} onClick={() => onChange(!on)} />;
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

/** 打开着的弹层（最上面的在末尾）：Esc 只关最上面那层（v1.16）。 */
const openSheets: symbol[] = [];

/** 遮罩贴住“真正看得见的那块”（v2.93）：手机浏览器的工具栏、软键盘会把可见区域缩小，而 position: fixed; inset: 0 仍按整块布局视口算，
 *  弹层底部的取消 / 创建就被挡住。这里把 visualViewport 的偏移和高度写进遮罩的 --vv-top / --vv-h（ui.css 用它们定位）；
 *  没有 visualViewport 的浏览器不写，CSS 退回 100dvh。 */
function useVisualViewport(el: RefObject<HTMLElement | null>) {
  useEffect(() => {
    const vv = window.visualViewport;
    const node = el.current;
    if (!vv || !node) return;
    let frame = 0;
    const apply = () => {
      frame = 0;
      node.style.setProperty("--vv-top", `${vv.offsetTop}px`);
      node.style.setProperty("--vv-h", `${vv.height}px`);
    };
    const schedule = () => { if (!frame) frame = requestAnimationFrame(apply); };
    apply();
    vv.addEventListener("resize", schedule);
    vv.addEventListener("scroll", schedule);
    return () => { vv.removeEventListener("resize", schedule); vv.removeEventListener("scroll", schedule); cancelAnimationFrame(frame); };
  }, [el]);
}

/** 弹层：桌面 = 居中浮起的玻璃卡；手机（≤860，v3.5.1 用户“别留那个半屏的”）= 铺满整屏、直接落在壁纸上的一页（= 子页的样子：
 *  左上圆玻璃返回钮、标题居中裸字、内容整页可滚、按钮行贴底），下面的页面淡出让位（<html data-sheet>，ui.css），旧的底部半屏卡已删。
 *  v2.93：portal 到 body——以前渲染在页面树里，页面的顶部渐隐 mask 和入场 transform 各自形成层叠上下文，z-index 50 也压不过外壳顶栏（20）和底部输入胶囊（16）。
 *  层级统一在 ui.css：输入胶囊 16 < 顶栏 20 < 抽屉 30 < 弹层 50 < 对话框 60。按钮行（actions 或子内容里的 .sheet-actions）贴底常驻。
 *  手机上滚过标题行 / 按钮行的内容由两条壁纸副本（SkyFade）渐隐，和子页、输入胶囊同一画法；桌面不显示它们。 */
export function Sheet({ title, onClose, children, actions }: { title: string; onClose: () => void; children: ReactNode; actions?: ReactNode }) {
  const box = useRef<HTMLDivElement>(null);
  const scrim = useRef<HTMLDivElement>(null);
  const close = useRef(onClose);
  close.current = onClose;
  const [footH, setFootH] = useState(0);
  useVisualViewport(scrim);
  // 按钮行可能来自 actions，也可能在子内容里（ProjectForm）：量它的实高给底部渐隐条
  useLayoutEffect(() => {
    const bar = box.current?.querySelector<HTMLElement>(".sheet-actions");
    if (!bar) return;
    const report = () => setFootH(bar.offsetHeight);
    report();
    const ro = new ResizeObserver(report);
    ro.observe(bar);
    return () => ro.disconnect();
  }, []);
  // v1.16：弹层是模态框——打开时焦点移进来（键盘/读屏从标题开始），Esc 关最上面一层，关掉后焦点回到打开它的键。
  useEffect(() => {
    const me = Symbol("sheet");
    openSheets.push(me);
    document.documentElement.dataset.sheet = "";
    const back = document.activeElement as HTMLElement | null;
    if (!box.current?.contains(document.activeElement)) box.current?.focus({ preventScroll: true });
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape" || openSheets[openSheets.length - 1] !== me || e.defaultPrevented) return;
      e.preventDefault();
      close.current();
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      openSheets.splice(openSheets.indexOf(me), 1);
      if (!openSheets.length) delete document.documentElement.dataset.sheet;
      if (back?.isConnected) back.focus({ preventScroll: true });
    };
  }, []);
  return createPortal(
    <div ref={scrim} className="sheet-scrim" onClick={onClose}>
      <div ref={box} tabIndex={-1} className="sheet" onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true" aria-label={title}>
        <header className="sheet-head">
          <button className="glass-btn glass sheet-close" onClick={onClose} aria-label="关闭" title="关闭（Esc）"><IconBack /></button>
          <h2>{title}</h2>
        </header>
        {children}
        {actions && <div className="sheet-actions">{actions}</div>}
      </div>
      <SkyFade kind="sheet" />
      {footH > 0 && <SkyFade kind="footer" height={footH + 16} />}
    </div>,
    document.body,
  );
}

/** 圆角搜索框（对话历史、记忆页共用）：有字时给清空键，Esc 清空。与 App SearchField 同款。 */
export function SearchField({ value, onChange, placeholder, className = "", onEnter }: { value: string; onChange: (v: string) => void; placeholder: string; className?: string; onEnter?: () => void }) {
  return (
    <label className={`search-field ${className}`}>
      <IconSearch />
      <input enterKeyHint="search" value={value} onChange={(e) => onChange(e.target.value)} placeholder={placeholder} aria-label={placeholder}
        onKeyDown={(e) => { if (e.key === "Escape") onChange(""); else if (e.key === "Enter" && onEnter) { e.preventDefault(); onEnter(); } }} />
      {value && <button className="icon-btn sm" aria-label="清空" onClick={() => onChange("")}><IconClose /></button>}
    </label>
  );
}

/** 搜索词：与后端 chat_search.terms、App searchTerms 同规则——空格分开、引号里当一个词、不分大小写去重、最多 6 个。 */
export function searchTerms(query: string): string[] {
  const quote = /"([^"]+)"|“([^”]+)”|「([^」]+)」/g;
  const q = query.trim();
  const out = [...q.matchAll(quote)].map((m) => (m[1] ?? m[2] ?? m[3] ?? "").trim());
  out.push(...q.replace(quote, " ").split(/\s+/));
  const seen = new Set<string>();
  return out.filter((t) => t && !seen.has(t.toLowerCase()) && seen.add(t.toLowerCase())).slice(0, 6);
}

/** 把每个搜索词在 text 里的所有出现（不分大小写）标亮，同一位置取最长的词。与 App 的 highlightSpans 同规则。 */
export function Highlight({ text, q }: { text: string; q: string }) {
  const words = searchTerms(q).map((t) => t.toLowerCase()).sort((a, b) => b.length - a.length);
  if (!words.length) return <>{text}</>;
  const out: ReactNode[] = [];
  const lower = text.toLowerCase();
  let from = 0;
  let i = 0;
  while (i < lower.length) {
    const w = words.find((x) => lower.startsWith(x, i));
    if (!w) { i++; continue; }
    if (i > from) out.push(text.slice(from, i));
    out.push(<mark key={i} className="hl">{text.slice(i, i + w.length)}</mark>);
    i = from = i + w.length;
  }
  out.push(text.slice(from));
  return <>{out}</>;
}

export type MenuItem = { label: string; icon?: ReactNode; danger?: boolean; checked?: boolean; hint?: string; onSelect: () => void };

/** 小弹出菜单：点触发按钮开，点外面 / Esc / 选中后关。全站唯一的弹出选择（v2.86 起取代原生 <select>：系统下拉白底宋体，和界面割裂）。
 *  选档用法：items 带 checked（当前项打勾）和 hint（一行说明）；triggerClass 让触发键用调用方的样式（如输入框里的模型钮）；align 决定贴左还是贴右。 */
export function Menu({ trigger, items, label = "更多", triggerClass = "icon-btn sm", align = "right" }: {
  trigger: ReactNode; items: MenuItem[]; label?: string; triggerClass?: string; align?: "left" | "right";
}) {
  const [open, setOpen] = useState(false);
  const [place, setPlace] = useState<CSSProperties | null>(null);
  const ref = useRef<HTMLDivElement>(null);
  const pop = useRef<HTMLDivElement>(null);
  // v1.12：菜单浮在 body 上（position: fixed），不再被卡片 / 列表组的 overflow 裁掉；下方放不下就往上翻
  useLayoutEffect(() => {
    if (!open) { setPlace(null); return; }
    const t = ref.current?.getBoundingClientRect();
    const h = pop.current?.offsetHeight ?? 0;
    if (!t) return;
    const gap = 4;
    const side: CSSProperties = align === "left" ? { left: Math.max(gap, t.left) } : { right: Math.max(gap, window.innerWidth - t.right) };
    const below = t.bottom + gap + h <= window.innerHeight - gap;
    setPlace(below ? { ...side, top: t.bottom + gap, transformOrigin: `top ${align}` }
                   : { ...side, bottom: window.innerHeight - t.top + gap, transformOrigin: `bottom ${align}` });
  }, [open, align]);
  useEffect(() => {
    if (!open) return;
    const close = (e: Event) => {
      const inside = (n: EventTarget | null) => !!n && (ref.current?.contains(n as Node) || pop.current?.contains(n as Node));
      if (e instanceof KeyboardEvent ? e.key === "Escape" : !inside(e.target)) {
        if (e instanceof KeyboardEvent) e.preventDefault(); // Esc 先关菜单，别连带关掉菜单所在的弹层（Sheet 跳过已处理的 Esc）
        setOpen(false);
      }
    };
    const away = () => setOpen(false); // 页面滚动 / 窗口变化：菜单会和触发键脱节，直接收起
    document.addEventListener("pointerdown", close);
    document.addEventListener("keydown", close, true);
    window.addEventListener("resize", away);
    document.addEventListener("scroll", away, true);
    return () => {
      document.removeEventListener("pointerdown", close); document.removeEventListener("keydown", close, true);
      window.removeEventListener("resize", away); document.removeEventListener("scroll", away, true);
    };
  }, [open]);
  return (
    <div className={`menu ${open ? "open" : ""}`} ref={ref} onClick={(e) => e.stopPropagation()}>
      <button className={`${triggerClass} menu-trigger`} aria-label={label} aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen((o) => !o)}>{trigger}</button>
      {open && createPortal(
        <div className={`menu-pop ${place ? "placed" : ""}`} role="menu" aria-label={label} ref={pop} style={place ?? undefined}
          onClick={(e) => e.stopPropagation()}>
          {items.map((it) => (
            <button key={it.label} role={it.checked === undefined ? "menuitem" : "menuitemradio"} aria-checked={it.checked}
              className={`menu-item ${it.danger ? "danger" : ""} ${it.checked ? "checked" : ""}`}
              onClick={() => { setOpen(false); it.onSelect(); }}>
              {it.icon}
              {it.hint ? <span className="menu-item-text"><span>{it.label}</span><small>{it.hint}</small></span> : it.label}
              {it.checked && <span className="menu-item-check"><IconCheck size={16} /></span>}
            </button>
          ))}
        </div>,
        document.body,
      )}
    </div>
  );
}
