import { useContext, useEffect, useLayoutEffect, useRef, useState, type AnimationEvent, type ContextType, type CSSProperties, type ReactNode } from "react";
import { UNSAFE_LocationContext, useLocation, useOutlet } from "react-router-dom";
import { InboxProvider } from "../hooks/useInbox";
import InboxBanner from "./InboxBanner";
import { ShellLeadSlot } from "./ShellLead";
import TopBar, { ME, isShellRoot } from "./TopBar";
import "./shell.css";

/** 整个应用的骨架（设计 v2）：渐变底（body）→ 当前页面（铺满全屏）→ 浮动顶栏。
 *  一级页面（主页 / 聊天 / 项目 / 项目页 / “我的”）通过 --inset-top 让出顶栏的高度，内容从顶栏下面滚过去；子页面自带返回钮和标题。收件箱提醒也挂在这一层。 */
export default function AppShell() {
  return <InboxProvider><Shell /></InboxProvider>;
}

function Shell() {
  const { pathname } = useLocation();
  const bar = isShellRoot(pathname);
  return (
    <div className={`shell ${bar ? "has-bar" : ""}`}>
      <a className="skip-link" href="#main">跳到主要内容</a>
      <ShellViews />
      {bar && <TopBar />}
      <InboxBanner />
    </div>
  );
}

/** 横滑时长兜底：动画结束事件没来（标签页在后台等）也按时卸掉离场页。= --dur-slow 360ms + 余量。 */
const SLIDE_GUARD_MS = 600;

type LocationCtx = ContextType<typeof UNSAFE_LocationContext>;
type Slide = { from: ReactNode; fromCtx: LocationCtx; fromKey: number; dir: 1 | -1 };

/** 只有一端是“我的”、另一端是带顶栏的一级页时横滑（= App ShellBranches 的 crossesMe）；三个分段之间、子页进出直接切。 */
const crossesMe = (a: string, b: string) => isShellRoot(a) && isShellRoot(b) && (a === ME) !== (b === ME);

/** 页面容器（v3.5.1，= App app_shell.dart ShellBranches）：进出“我的”时整页横滑——去“我的”= 当前页向左滑出、“我的”从右滑入，回去反向。
 *  路由仍只有一个 Outlet：横滑时把离场页的元素连同它当时的 location 多留一段（UNSAFE_LocationContext 冻住，滑出途中不按新地址重算），
 *  两层各自 transform（shell.css .shell-view.slide），滑完离场层卸载。只动 transform；减少动态、滑到一半又切走都直接到位。
 *  层的 key 只在横滑时换：其余导航（项目 A → 项目 B 等）组件照旧复用、不重挂。 */
function ShellViews() {
  const ctx = useContext(UNSAFE_LocationContext);
  const pathname = ctx.location.pathname;
  const outlet = useOutlet();
  const shown = useRef({ el: outlet, ctx }); // 上一次提交到屏幕上的页（横滑时离场的就是它）
  const [cur, setCur] = useState({ path: pathname, key: 0 });
  const [slide, setSlide] = useState<Slide | null>(null);

  // 地址变了：在这一次渲染里就定下要不要滑（React“记住上一次渲染的值”的写法），不会先闪一帧只有新页。
  if (cur.path !== pathname) {
    const go = crossesMe(cur.path, pathname) && !matchMedia("(prefers-reduced-motion: reduce)").matches;
    setSlide(go ? { from: shown.current.el, fromCtx: shown.current.ctx, fromKey: cur.key, dir: pathname === ME ? 1 : -1 } : null);
    setCur({ path: pathname, key: go ? cur.key + 1 : cur.key });
  }
  useLayoutEffect(() => { shown.current = { el: outlet, ctx }; });

  useEffect(() => {
    if (!slide) return;
    const t = window.setTimeout(() => setSlide(null), SLIDE_GUARD_MS);
    return () => window.clearTimeout(t);
  }, [slide]);

  const done = (e: AnimationEvent) => { if (e.target === e.currentTarget) setSlide(null); }; // 页里元素自己的进场动画也会冒泡上来
  const vars = slide && ({ ["--slide-dir" as string]: slide.dir } as CSSProperties);
  return (
    <main id="main" className={`shell-main ${slide ? "sliding" : ""}`} tabIndex={-1}>
      {slide && <ShellView key={slide.fromKey} className="shell-view slide out" style={vars!} ctx={slide.fromCtx} out>{slide.from}</ShellView>}
      <ShellView key={cur.key} className={`shell-view ${slide ? "slide in" : ""}`} style={vars || undefined} ctx={ctx} onAnimationEnd={slide ? done : undefined}>
        {outlet}
      </ShellView>
    </main>
  );
}

/** 一层页面 + 它自己的顶栏左钮槽（v3.5.5，= App ShellPage 的 lead 画在页面里）：左钮属于页面，所以放在页面这一层里、
 *  定位到顶栏左格的同一位置（shell.css .shell-lead）。进出“我的”横滑时它跟着本页一起滑走 / 滑进，不再钉在顶栏上等离场页卸载才消失。
 *  槽只在本层是带顶栏的一级页时挂出（LeadSlot）；层的 key 不变时槽和页面一起复用。 */
function ShellView({ ctx, out, children, ...rest }: { ctx: LocationCtx; out?: boolean; children: ReactNode; className: string; style?: CSSProperties; onAnimationEnd?: (e: AnimationEvent) => void }) {
  const [slot, setSlot] = useState<HTMLElement | null>(null);
  const bar = isShellRoot(ctx.location.pathname);
  return (
    <div {...rest} {...(out ? { "aria-hidden": true, inert: "" } : {})}>
      <ShellLeadSlot.Provider value={bar ? slot : null}>
        <UNSAFE_LocationContext.Provider value={ctx}>{children}</UNSAFE_LocationContext.Provider>
      </ShellLeadSlot.Provider>
      {bar && <LeadSlot onSlot={setSlot} quiet={rest.className.includes("slide")} />}
    </div>
  );
}

/** 槽本身。和顶栏一起出现（从子页回到一级页、首次打开）时同一个 float-in 浮入；随横滑进来的那层不浮入——
 *  顶栏没动，左钮跟着页面滑进来就够了（= App）。是否浮入只在槽挂上那一刻定，滑完摘掉 slide 类也不会补播。 */
function LeadSlot({ onSlot, quiet }: { onSlot: (el: HTMLElement | null) => void; quiet: boolean }) {
  const [cls] = useState(quiet ? "shell-lead" : "shell-lead float");
  return <div className={cls} ref={onSlot} />;
}
