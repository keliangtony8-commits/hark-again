import { useState } from "react";
import type { ScheduledTask } from "../../lib/types";
import { usesModel } from "../../lib/taskLabels";
import { IconBrain, IconChevron, IconDoc, IconTrash } from "../../ui/icons";
import { ListGroup, Section, Sheet } from "../../ui/kit";
import CopyButton from "../../ui/CopyButton";
import { confirmDialog } from "../../ui/dialog";

/** v2.13 定时任务详情里的“助手记下的”：做法（第一次运行写下的步骤 / 来源）与观察（之后滚动改的经验），
 *  每次运行开头助手都会读到（后端 app/task_brief.py）。只看全文和清空（PATCH {runbook|note: ""}）；改写交给助手。
 *  与 App features/me/task_memory.dart 同版面同文案；定时脚本没有这一块，两项都没有时整块不出现。 */
type Memo = { field: "runbook" | "note"; title: string; hint: string; text: string };

const memosOf = (t: ScheduledTask): Memo[] => !usesModel(t) ? [] : [
  ...(t.runbook ? [{ field: "runbook" as const, title: "做法", hint: "第一次运行时写下的步骤和来源，之后照着做", text: t.runbook }] : []),
  ...(t.note ? [{ field: "note" as const, title: "观察", hint: "几次运行之间记下的经验", text: t.note }] : []),
];

export default function TaskMemory({ task, onClear }: { task: ScheduledTask; onClear: (field: Memo["field"]) => Promise<void> }) {
  const [open, setOpen] = useState<Memo | null>(null);
  const memos = memosOf(task);
  if (!memos.length) return null;
  const clear = async (m: Memo) => {
    if (!(await confirmDialog({ title: `清空${m.title}？`, text: "下次运行时助手会重新摸索、重新记。", action: "清空" }))) return;
    await onClear(m.field);
    setOpen(null);
  };
  return (
    <Section title="助手记下的">
      <ListGroup className="task-memo">
        {memos.map((m, i) => (
          <button key={m.field} className="row run-row" style={{ animationDelay: `calc(var(--stagger) * ${i})` }}
            aria-label={`${m.title}：${m.text.slice(0, 80)}，看全文`} onClick={() => setOpen(m)}>
            <span className="run-status" aria-hidden>{m.field === "runbook" ? <IconDoc size={14} /> : <IconBrain size={14} />}</span>
            <span className="row-body">
              <span className="row-title">{m.title}</span>
              <span className="row-sub task-memo-preview">{m.text}</span>
            </span>
            <IconChevron />
          </button>
        ))}
      </ListGroup>
      {open && (
        <Sheet title={open.title} onClose={() => setOpen(null)} actions={<>
          <CopyButton text={open.text} />
          <button className="btn btn-ghost btn-sm danger-text" onClick={() => clear(open)}><IconTrash />清空</button>
        </>}>
          <p className="form-note">{open.hint}</p>
          <p className="task-memo-full">{open.text}</p>
        </Sheet>
      )}
    </Section>
  );
}
