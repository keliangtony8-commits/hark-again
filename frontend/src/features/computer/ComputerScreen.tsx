import { type ReactNode, memo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useSwr } from "../../hooks/useSwr";
import { BROWSER_SESSIONS_PATH, type BrowserSessionList, browserSessionExpired } from "../../lib/browserSessions";
import { COMPUTER_MEMORY_TIGHT, type ComputerStatus, computerIntro, diskFull, diskTight, memoryViewOf } from "../../lib/computer";
import { formatSize } from "../../lib/files";
import { HOST_PATH, HOST_SECTION_TITLE, type HostStatus } from "../../lib/host";
import { PERSONAL_WORKSPACE, isPersonalWorkspace } from "../../lib/workspace";
import { IconBack, IconChevron, IconChip, IconDisk, IconGlobe, IconLayout, IconShield, IconTerminal } from "../../ui/icons";
import { ListGroup, ListRow, Page, PageHeader } from "../../ui/kit";
import PagesScreen from "../me/PagesScreen";
import ProjectFiles from "../projects/ProjectFiles";
import BrowserSessionsSection from "./BrowserSessionsSection";
import HostSection from "./HostSection";
import { DiskJobsSection, MemorySection, PortsSection, ProcessSection, StorageSection } from "./ComputerDetails";
import { ComputerRestartButton, ComputerStatusGroup } from "./ComputerSection";
import { ComputerPoll, useComputerSelect, useLate } from "./useComputer";

/** 电脑详情页（= App features/computer/computer_screen.dart，v3.5.1 d8a2d73）：我的 → 我的电脑（个人工作区）和项目首屏点“电脑”进来的
 *  /projects/:pid/computer 共用。原来约 4.7 屏长、内存 / 服务重复出现，改成一屏概览 + 子页，能力一样不少：
 *    标题行右侧圆玻璃钮“重启”（只在运行中给，确认不变）
 *    状态分组：运行中、CPU / 内存 / 文件、内存条、打满警示 +“整台服务器”，同组接着常驻服务 + 后台任务，只露前 3 行，多了“全部 N 个 ›”进子页 tasks
 *    一组导航行（行尾一个值，紧张 = 警示色、已满 = 危险色）：端口 / 内存 / 正在运行的程序 / 磁盘（+ 个人电脑的 浏览器登录 / Pages / 主机模式）
 *    页底一行小字：这台电脑是什么（原页头说明）。
 *  子页 /me/computer/:part、/projects/:pid/computer/:part = ComputerDetailScreen，复用原来那一节（不重复节标题）；“清理”和“最近 7 天谁写得最多”在磁盘子页。
 *  设置搜索（meIndex.ts）的 disk / browser-logins / host 定位到这里对应的导航行（ListRow spot）。
 *  轮询在 ComputerPoll（useComputer.ts）；每一行 memo + 只取自己显示的值，轮询回来只有变了的行重渲染。 */

const PARTS: Record<string, string> = {
  tasks: "后台任务",
  ports: "正在监听的端口",
  memory: "内存",
  processes: "正在运行的程序",
  disk: "磁盘",
  "browser-logins": "浏览器登录",
  host: HOST_SECTION_TITLE,
};
const PERSONAL_ONLY = new Set(["browser-logins", "host", "pages"]);

const basePath = (ws: string) => (isPersonalWorkspace(ws) ? "/me/computer" : `/projects/${ws}/computer`);

/** 标题行（= PageHeader 的版式）：左返回钮、居中标题，右侧单独一颗圆玻璃钮“重启”（和返回钮对称，不是动作胶囊）。 */
function ComputerHeader({ title, ws }: { title: string; ws: string }) {
  const nav = useNavigate();
  return (
    <header className="page-head computer-head">
      <button className="glass-btn glass" onClick={() => nav(-1)} aria-label="返回" title="返回"><IconBack /></button>
      <h1>{title}</h1>
      <ComputerRestartButton ws={ws} />
    </header>
  );
}

type Tone = "none" | "warning" | "danger";
type Value = { text: string; tone: Tone } | null;

const portsValue = (s: ComputerStatus | undefined): Value =>
  s && s.sandbox.state === "running" ? { text: `${(s.ports ?? []).length} 个`, tone: "none" } : null;
const processesValue = (s: ComputerStatus | undefined): Value =>
  s && s.sandbox.state === "running" ? { text: `${(s.sandbox.processes ?? []).length} 个`, tone: "none" } : null;
function memoryValue(s: ComputerStatus | undefined): Value {
  if (!s || s.sandbox.state !== "running") return null;
  const used = s.memory?.used ?? s.sandbox.memory_used;
  const limit = s.memory?.limit ?? s.sandbox.memory_limit;
  if (used == null) return null;
  const ratio = limit == null || limit <= 0 ? 0 : used / limit;
  const tone: Tone = (s.sandbox.oom_kills ?? 0) > 0 || ratio >= 0.98 ? "danger" : ratio >= COMPUTER_MEMORY_TIGHT ? "warning" : "none";
  return { text: `${formatSize(used)}${limit != null ? ` / ${formatSize(limit)}` : ""}`, tone };
}
const diskValue = (s: ComputerStatus | undefined): Value => s ? {
  text: `${formatSize(s.disk_used)}${s.disk_partial ? "+" : ""}${s.disk_limit != null ? ` / ${formatSize(s.disk_limit)}` : ""}`,
  tone: diskFull(s) ? "danger" : diskTight(s) ? "warning" : "none",
} : null;

/** 行尾：一个值（按档位着色，换了淡入）+ 箭头。 */
const Trail = ({ v }: { v: Value }) => (
  <>{v && <span key={v.text} className={`computer-val is-${v.tone}`}>{v.text}</span>}<IconChevron /></>
);

/** 一行导航：只订阅自己行尾那个值。 */
const NavRow = memo(function NavRow({ ws, to, icon, title, spot, pick }:
  { ws: string; to: string; icon: ReactNode; title: string; spot?: string; pick: (s: ComputerStatus | undefined) => Value }) {
  const v = useComputerSelect(ws, pick);
  return <ListRow className="computer-nav-row" to={to} icon={icon} title={title} spot={spot} trail={<Trail v={v} />} />;
});

const BrowserNavRow = memo(function BrowserNavRow({ to }: { to: string }) {
  const { data } = useSwr<BrowserSessionList>(BROWSER_SESSIONS_PATH);
  const v: Value = data ? { text: `${data.sessions.length} 个网站`, tone: data.sessions.some(browserSessionExpired) ? "warning" : "none" } : null;
  return <ListRow className="computer-nav-row" to={to} icon={<IconGlobe />} title="浏览器登录" spot="browser-logins" trail={<Trail v={v} />} />;
});

const HostNavRow = memo(function HostNavRow({ to }: { to: string }) {
  const { data } = useSwr<HostStatus>(HOST_PATH);
  const v: Value = data ? { text: data.enabled ? "已打开" : "关闭", tone: "none" } : null;
  return <ListRow className="computer-nav-row" to={to} icon={<IconShield />} title="主机模式" spot="host" trail={<Trail v={v} />} />;
});

/** 页底一行小字：这台电脑是什么（v2.85 原页头说明）。 */
const Intro = memo(function Intro({ ws }: { ws: string }) {
  const personal = isPersonalWorkspace(ws);
  const line = useComputerSelect(ws, (s) => computerIntro(s, personal));
  return <p className="computer-intro">{line}</p>;
});

const NavGroup = memo(function NavGroup({ ws }: { ws: string }) {
  const personal = isPersonalWorkspace(ws);
  const base = basePath(ws);
  const late = useLate();
  return (
    <ListGroup className="computer-nav" enter={late ? undefined : 2}>
      <NavRow ws={ws} to={`${base}/ports`} icon={<IconGlobe />} title="端口" pick={portsValue} />
      <NavRow ws={ws} to={`${base}/memory`} icon={<IconChip />} title="内存" pick={memoryValue} />
      <NavRow ws={ws} to={`${base}/processes`} icon={<IconTerminal />} title="正在运行的程序" pick={processesValue} />
      <NavRow ws={ws} to={`${base}/disk`} icon={<IconDisk />} title="磁盘" spot="disk" pick={diskValue} />
      {personal && <BrowserNavRow to={`${base}/browser-logins`} />}
      {personal && <ListRow className="computer-nav-row" to="/me/pages" icon={<IconLayout />} title="Pages" />}
      {personal && <HostNavRow to={`${base}/host`} />}
    </ListGroup>
  );
});

export default function ComputerScreen() {
  const { pid } = useParams();
  const ws = pid ?? PERSONAL_WORKSPACE;
  const personal = isPersonalWorkspace(ws);
  return (
    <Page className="computer-page" header={<ComputerHeader title={personal ? "我的电脑" : "项目的电脑"} ws={ws} />}>
      <ComputerPoll ws={ws} pollAlways>
        <ComputerStatusGroup ws={ws} limit={3} allTo={`${basePath(ws)}/tasks`} enter={1} />
        <NavGroup ws={ws} />
        <Intro ws={ws} />
      </ComputerPoll>
    </Page>
  );
}

/** 子页里这一节没东西时说一句（原节空时整块不画，单独成页就成了白屏）。还没加载完不说。 */
function OrEmpty({ ws, empty, text, children }: { ws: string; empty: (s: ComputerStatus) => boolean; text: string; children: ReactNode }) {
  const none = useComputerSelect(ws, (s) => !!s && empty(s));
  return none ? <p className="computer-empty">{text}</p> : <>{children}</>;
}

/** 子页（v3.5.1）：/me/computer/:part、/projects/:pid/computer/:part。复用原来各节（不画节标题，页标题就是节名）。 */
export function ComputerDetailScreen() {
  const { pid, part = "" } = useParams();
  const ws = pid ?? PERSONAL_WORKSPACE;
  const personal = isPersonalWorkspace(ws);
  const [files, setFiles] = useState(false);
  if (part === "pages" && personal) return <PagesScreen />;
  const known = Object.prototype.hasOwnProperty.call(PARTS, part) && (personal || !PERSONAL_ONLY.has(part));
  let body: ReactNode;
  if (!known) body = <p className="computer-empty">没有这一页</p>;
  else if (part === "tasks") body = (
    <OrEmpty ws={ws} empty={(s) => !(s.services ?? []).length && !s.running_jobs.length} text="没有正在运行的服务和后台任务">
      <ComputerStatusGroup ws={ws} status={false} enter={0} />
    </OrEmpty>);
  else if (part === "ports") body = (
    <OrEmpty ws={ws} empty={(s) => s.sandbox.state !== "running" || !(s.ports ?? []).length} text="没有正在监听的端口">
      <PortsSection ws={ws} titled={false} enter={0} />
    </OrEmpty>);
  else if (part === "memory") body = (
    <OrEmpty ws={ws} empty={(s) => memoryViewOf(s) == null} text="电脑没在运行，暂时看不到内存占用">
      <MemorySection ws={ws} titled={false} enter={0} />
    </OrEmpty>);
  else if (part === "processes") body = (
    <OrEmpty ws={ws} empty={(s) => s.sandbox.state !== "running" || !(s.sandbox.processes ?? []).length} text="没有正在运行的程序">
      <ProcessSection ws={ws} titled={false} enter={0} />
    </OrEmpty>);
  else if (part === "disk") body = (<>
    <StorageSection ws={ws} titled={false} enter={0} onFiles={() => setFiles(true)} />
    <DiskJobsSection ws={ws} enter={1} />
    {files && <ProjectFiles projectId={ws} onClose={() => setFiles(false)} />}
  </>);
  else if (part === "browser-logins") body = <BrowserSessionsSection titled={false} enter={0} />;
  else body = <HostSection titled={false} enter={0} />;
  const computer = known && part !== "browser-logins" && part !== "host";
  return (
    <Page className="computer-page" header={<PageHeader title={PARTS[part] ?? (personal ? "我的电脑" : "项目的电脑")} back />}>
      {computer ? <ComputerPoll ws={ws} pollAlways>{body}</ComputerPoll> : body}
    </Page>
  );
}
