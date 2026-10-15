import { useState } from "react";
import { useParams } from "react-router-dom";
import { computerIntro, computerStateLabel } from "../../lib/computer";
import { PERSONAL_WORKSPACE, isPersonalWorkspace } from "../../lib/workspace";
import { IconLayout } from "../../ui/icons";
import { ListGroup, ListRow, Page, PageHeader, PageIntro } from "../../ui/kit";
import ProjectFiles from "../projects/ProjectFiles";
import BrowserSessionsSection from "./BrowserSessionsSection";
import HostSection from "./HostSection";
import { DiskJobsSection, MemorySection, PortsSection, ProcessSection, StorageSection } from "./ComputerDetails";
import ComputerSection from "./ComputerSection";
import { useComputer } from "./useComputer";

/** 电脑详情页（= App features/computer/computer_screen.dart）：我的 → 我的电脑（个人工作区）和项目首屏点“电脑”进来的
 *  /projects/:pid/computer（v1.27）共用。状态（运行中一直刷新）→ 端口 → 内存（v1.94 谁占的）→ 正在运行的程序 → 磁盘（拆分、文件、装过的工具、清理）
 *  → 个人电脑才有的浏览器登录（v1.26）。几节共用一份 useComputer。 */
export default function ComputerScreen() {
  const { pid } = useParams();
  const ws = pid ?? PERSONAL_WORKSPACE;
  const personal = isPersonalWorkspace(ws);
  const ctl = useComputer(ws, true);
  const [files, setFiles] = useState(false);
  const s = ctl.s;
  return (
    <Page header={<PageHeader title={personal ? "我的电脑" : "项目的电脑"} back />}>
      <PageIntro loading={s === undefined} summary={s ? computerStateLabel(s.sandbox.state) : "暂时看不到状态"}
        line={computerIntro(s, personal)} />
      <ComputerSection ws={ws} title="状态" enter={1} ctl={ctl} />
      <PortsSection ws={ws} ctl={ctl} enter={2} />
      <MemorySection ctl={ctl} enter={3} />
      <ProcessSection ctl={ctl} enter={4} />
      <StorageSection ws={ws} ctl={ctl} enter={5} onFiles={() => setFiles(true)} />
      <DiskJobsSection ctl={ctl} enter={6} />
      {personal && <ListGroup className="me-group" enter={7}><ListRow to="/me/pages" icon={<IconLayout />} title="Pages" /></ListGroup>}
      {personal && <BrowserSessionsSection enter={7} />}
      {personal && <HostSection enter={8} />}
      {files && <ProjectFiles projectId={ws} onClose={() => setFiles(false)} />}
    </Page>
  );
}
