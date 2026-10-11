import { NavLink, useLocation, useNavigate } from "react-router-dom";
import { useInbox } from "../hooks/useInbox";
import { Avatar } from "../ui/glass";

/** 一级栏目。新增一级栏目只改这里（“我的”不是栏目：点右上角头像进入）。 */
export const SEGMENTS = [
  { to: "/", label: "主页", end: true },
  { to: "/chat", label: "聊天" },
  { to: "/projects", label: "项目" },
];

/** 只有在这些路径上才显示浮动顶栏；进项目对话、“我的”及其子页面时让位给页面自己的标题栏。 */
export const isShellRoot = (path: string) => SEGMENTS.some((s) => s.to === path);

/** 浮动顶栏：左 = 页面的上下文按钮槽，中 = 分段导航（实心胶囊滑过去），右 = 头像 → 我的。 */
export default function TopBar({ leadRef }: { leadRef: (el: HTMLDivElement | null) => void }) {
  const { pathname } = useLocation();
  const nav = useNavigate();
  const { summary } = useInbox();
  const i = Math.max(0, SEGMENTS.findIndex((s) => s.to === pathname));
  return (
    <header className="topbar">
      <div className="topbar-lead" ref={leadRef} />
      <nav className="segments glass" aria-label="主导航" style={{ ["--n" as string]: SEGMENTS.length, ["--i" as string]: i }}>
        <span className="segments-thumb" aria-hidden />
        {SEGMENTS.map(({ to, label, end }) => (
          <NavLink key={to} to={to} end={end} className={({ isActive }) => `segment ${isActive ? "on" : ""}`}>
            <span className="segment-label">
              {label}
              {to === "/" && summary.unread > 0 && <i className="segment-dot" aria-hidden />}
            </span>
            {to === "/" && summary.unread > 0 && <span className="sr-only">，{summary.unread} 条未读</span>}
          </NavLink>
        ))}
      </nav>
      <div className="topbar-trail"><Avatar onClick={() => nav("/me")} label="我的" /></div>
    </header>
  );
}
