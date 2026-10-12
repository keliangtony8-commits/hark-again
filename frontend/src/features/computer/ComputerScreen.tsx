import { useState } from "react";
import { useParams } from "react-router-dom";
import { computerStateLabel } from "../../lib/computer";
import { PERSONAL_WORKSPACE, isPersonalWorkspace } from "../../lib/workspace";
import { Page, PageHeader, PageIntro } from "../../ui/kit";
import ProjectFiles from "../projects/ProjectFiles";
import BrowserSessionsSection from "./BrowserSessionsSection";
import { PortsSection, ProcessSection, StorageSection } from "./ComputerDetails";
import ComputerSection from "./ComputerSection";
import { useComputer } from "./useComputer";

/** 电脑详情页（= App features/computer/computer_screen.dart）：我的 → 我的电脑（个人工作区）和项目首屏点“电脑”进来的
 *  /projects/:pid/computer（v1.27）共用。状态（运行中一直刷新）→ 正在运行的程序 → 磁盘（拆分、文件、装过的工具、清理）
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
        line={personal ? "主聊天和定时任务用的云端 Linux：我在这里跑代码、装软件、做后台任务，产物放进“我的文件”。"
          : "这个项目专用的云端 Linux：项目里的对话都在这里跑代码、装软件、做后台任务，文件就是项目文件。"} />
      <ComputerSection ws={ws} title="状态" enter={1} ctl={ctl} />
      <PortsSection ws={ws} ctl={ctl} enter={2} />
      <ProcessSection ctl={ctl} enter={3} />
      <StorageSection ws={ws} ctl={ctl} enter={4} onFiles={() => setFiles(true)} />
      {personal && <BrowserSessionsSection enter={5} />}
      {files && <ProjectFiles projectId={ws} onClose={() => setFiles(false)} />}
    </Page>
  );
}
