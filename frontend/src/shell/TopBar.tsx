import { NavLink, useLocation, useNavigate } from "react-router-dom";
import { useInbox } from "../hooks/useInbox";
import { Avatar } from "../ui/glass";

/** 一级栏目 = 顶栏分段。新增一级栏目只改这里。“我的”是第四个标签（v3.5.1 照 Hark，= App meBranch）：不在分段里，由右上角头像进入。 */
export const SEGMENTS = [
  { to: "/", label: "主页", end: true },
  { to: "/chat", label: "聊天" },
  { to: "/projects", label: "项目" },
];

export const ME = "/me";
const PROJECT_PAGE = /^\/projects\/[^/]+$/;
/** 一级页面之外、顶栏照常显示的“目录”页（v3.5.2 照 Hark：聊天的对话目录，= App shellBarShown 的 _directories）。 */
const DIRECTORIES = ["/chat/history"];

/** 浮动顶栏在这些路径上显示：三个一级栏目 + “我的” + 对话目录 + 项目页（v2.93 §Q 项目对话也在一级外壳下，= App shellBarShown）；
 *  项目的“电脑”、“我的”里的各个子页面让位给页面自己的返回钮和标题。 */
export const isShellRoot = (path: string) => path === ME || SEGMENTS.some((s) => s.to === path) || DIRECTORIES.includes(path) || PROJECT_PAGE.test(path);

/** 当前路径属于哪个栏目（滑块位置）：/projects/:pid 仍算“项目”；“我的”不在分段里 → -1。 */
const segmentOf = (path: string) => SEGMENTS.findIndex((s) => (s.end ? s.to === path : path === s.to || path.startsWith(`${s.to}/`)));

/** 滑块上一次停的分段：在“我的”时滑块原位淡出、不跳；进出子页顶栏会重新挂载，所以记在模块里而不是组件状态里。 */
let lastSegment = 0;

/** 浮动顶栏：左 = 页面的上下文按钮槽，中 = 分段导航（实心胶囊滑过去），右 = 头像 → 我的。
 *  在“我的”时三个分段都不选中：滑块停在原位淡出，头像外圈淡入一道和滑块同色的环（= App top_bar.dart _AvatarTab）。 */
export default function TopBar({ leadRef }: { leadRef: (el: HTMLDivElement | null) => void }) {
  const { pathname } = useLocation();
  const nav = useNavigate();
  const { summary } = useInbox();
  const seg = segmentOf(pathname);
  const me = pathname === ME;
  if (seg >= 0) lastSegment = seg;
  return (
    <header className="topbar">
      <div className="topbar-lead" ref={leadRef} />
      <nav className="segments glass" aria-label="主导航" style={{ ["--n" as string]: SEGMENTS.length, ["--i" as string]: lastSegment }}>
        <span className={`segments-thumb ${seg < 0 ? "off" : ""}`} aria-hidden />
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
      <div className={`topbar-trail avatar-tab ${me ? "on" : ""}`}><Avatar onClick={() => nav(ME)} label="我的" current={me} /></div>
    </header>
  );
}
