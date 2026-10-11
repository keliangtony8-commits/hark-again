import { useState } from "react";
import { Outlet, useLocation } from "react-router-dom";
import { InboxProvider } from "../hooks/useInbox";
import InboxBanner from "./InboxBanner";
import { ShellLeadSlot } from "./ShellLead";
import TopBar, { isShellRoot } from "./TopBar";
import "./shell.css";

/** 整个应用的骨架（设计 v2）：渐变底（body）→ 当前页面（铺满全屏）→ 浮动顶栏。
 *  一级页面通过 --inset-top 让出顶栏的高度，内容从顶栏下面滚过去；子页面自带浮动标题栏。收件箱提醒也挂在这一层。 */
export default function AppShell() {
  return <InboxProvider><Shell /></InboxProvider>;
}

function Shell() {
  const { pathname } = useLocation();
  const bar = isShellRoot(pathname);
  const [lead, setLead] = useState<HTMLElement | null>(null);
  return (
    <ShellLeadSlot.Provider value={lead}>
      <div className={`shell ${bar ? "has-bar" : ""}`}>
        <a className="skip-link" href="#main">跳到主要内容</a>
        <main id="main" className="shell-main" tabIndex={-1}><Outlet /></main>
        {bar && <TopBar leadRef={setLead} />}
        <InboxBanner />
      </div>
    </ShellLeadSlot.Provider>
  );
}
