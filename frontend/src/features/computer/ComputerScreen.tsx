import { useCallback, useState } from "react";
import { type ComputerStatus, computerStateLabel } from "../../lib/computer";
import { PERSONAL_WORKSPACE, workspaceFilesTitle } from "../../lib/workspace";
import { IconChevron, IconFolder } from "../../ui/icons";
import { Page, PageHeader, PageIntro, Section } from "../../ui/kit";
import ProjectFiles from "../projects/ProjectFiles";
import ComputerSection from "./ComputerSection";

/** 我的 → 我的电脑（v1.25，= App features/computer/computer_screen.dart）：主聊天和定时任务用的那台云端 Linux。
 *  页头摘要 = 状态词 → “状态”一节（ComputerSection）→ 文件入口（我的文件抽屉）。 */
export default function ComputerScreen() {
  const [s, setS] = useState<ComputerStatus | null | undefined>(undefined);
  const [files, setFiles] = useState(false);
  const onStatus = useCallback((v: ComputerStatus | null) => setS(v), []);
  return (
    <Page header={<PageHeader title="我的电脑" back />}>
      <PageIntro loading={s === undefined} summary={s ? computerStateLabel(s.sandbox.state) : "暂时看不到状态"}
        line="主聊天和定时任务用的云端 Linux：我在这里跑代码、装软件、做后台任务，产物放进“我的文件”。" />
      <ComputerSection ws={PERSONAL_WORKSPACE} title="状态" enter={1} onStatus={onStatus} />
      <Section title="文件" enter={2}>
        <div className="list">
          <button className="row" onClick={() => setFiles(true)}>
            <span className="row-icon"><IconFolder /></span>
            <div className="row-body"><div className="row-title">{workspaceFilesTitle(PERSONAL_WORKSPACE)}</div>
              <div className="row-sub">这台电脑上的文件，我做出来的也在这</div></div>
            <span className="row-trail"><IconChevron /></span>
          </button>
        </div>
      </Section>
      {files && <ProjectFiles projectId={PERSONAL_WORKSPACE} onClose={() => setFiles(false)} />}
    </Page>
  );
}
