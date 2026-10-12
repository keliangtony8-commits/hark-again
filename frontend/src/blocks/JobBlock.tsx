import { useCallback, useEffect, useRef, useState } from "react";
import { http } from "../lib/api";
import { JOB_CPU_HOT, JOB_POLL_MS, JOB_REPLY_WAIT_MS, jobAutoStopped, jobCpuLabel, jobMemoryLabel, jobUsage, jobAwaitingReply, jobDuration, jobFootLabel, jobFromBlock, jobRunning, jobSemantics, jobStateLabel, jobTailLines, jobTone } from "../lib/jobs";
import type { JobBlock as T, JobInfo } from "../lib/types";
import { Sheet } from "../ui/kit";
import { IconAlert, IconCheck, IconCopy, IconStop } from "../ui/icons";
import { useBlockActions } from "./actions";

/** 后台任务卡（App blocks/job_block.dart 同一套行为）：运行中每 2 秒问一次进度、用时每秒本地跳、可取消；
 *  结束后等服务器在这段对话里接着说完（followup=pending），再让聊天页刷新一次——只在本卡亲眼看着它结束时触发，翻历史不会。 */
export default function JobBlock({ block }: { block: T }) {
  const { onJobSettled } = useBlockActions();
  const [job, setJob] = useState<JobInfo>(() => jobFromBlock(block));
  const [polledAt, setPolledAt] = useState(() => Date.now());
  const [, setTick] = useState(0);
  const [cancelling, setCancelling] = useState(false);
  const [showLog, setShowLog] = useState(false);
  const sawRunning = useRef(jobRunning(job));
  const endedAt = useRef<number | null>(null);
  const settled = useRef(false);
  const [polling, setPolling] = useState(jobRunning(job));

  const apply = useCallback((j: JobInfo) => {
    setJob(j);
    setPolledAt(Date.now());
    if (jobRunning(j)) return;
    endedAt.current ??= Date.now();
    if (jobAwaitingReply(j) && Date.now() - endedAt.current < JOB_REPLY_WAIT_MS) return;
    setPolling(false);
    if (sawRunning.current && !settled.current) {
      settled.current = true;
      onJobSettled?.();
    }
  }, [onJobSettled]);

  useEffect(() => {
    if (!polling) return;
    const ask = () => {
      if (document.hidden) return;
      http.get<JobInfo>(`/api/jobs/${block.id}`).then(apply).catch(() => {});
    };
    ask();
    const id = setInterval(ask, JOB_POLL_MS);
    const clock = setInterval(() => setTick((t) => t + 1), 1000);
    return () => { clearInterval(id); clearInterval(clock); };
  }, [polling, block.id, apply]);

  const cancel = async () => {
    setCancelling(true);
    try { apply(await http.post<JobInfo>(`/api/jobs/${block.id}/cancel`, {})); } catch { /* 下一次轮询会告诉真实状态 */ }
    setCancelling(false);
  };

  const running = jobRunning(job);
  const stopped = jobAutoStopped(job);
  const tone = jobTone(job.state, stopped);
  const elapsed = running ? job.elapsed + (Date.now() - polledAt) / 1000 : job.elapsed;
  const tail = jobTailLines(job.tail);
  const label = jobFootLabel(job);
  const usage = running ? jobUsage(job.usage) : null;
  return (
    <div className={`card blk-job tone-${tone}`} role="group" aria-label={jobSemantics(job, elapsed)}>
      <div className="blk-job-head">
        <span key={tone} className="blk-job-mark">
          {tone === "running" ? <i className="job-dot" /> : tone === "ok" ? <IconCheck size={16} /> : tone === "problem" ? <IconAlert size={16} /> : <IconStop size={14} />}
        </span>
        <span className="blk-job-title">{job.title}</span>
        <span className="blk-job-time" aria-hidden>{jobDuration(elapsed)}</span>
      </div>
      <div className="blk-job-cmd">$ {job.command.split("\n")[0]}</div>
      <pre className={`blk-job-log ${tail ? "" : "is-empty"}`}>{tail || (running ? "等待输出…" : "（没有输出）")}</pre>
      {stopped && <p className="blk-job-reason" aria-hidden>{job.stop_reason}</p>}
      {usage && (  /* v1.90 在跑时它占多少：问不到就不出现（不画成 0）；读屏句子已在卡片 aria-label 里 */
        <div className={`blk-job-usage ${usage.cpu >= JOB_CPU_HOT ? "is-hot" : ""}`} aria-hidden>
          <span className="blk-job-cpu">CPU {jobCpuLabel(usage.cpu)}</span>
          <div className="meter blk-job-meter"><span style={{ transform: `scaleX(${Math.min(1, usage.cpu / 100)})` }} /></div>
          <span className="blk-job-mem">{jobMemoryLabel(usage)}</span>
        </div>
      )}
      <div className="blk-job-foot">
        <span key={label} className="blk-job-state">{label}</span>
        {running
          ? <button className="btn btn-ghost btn-sm" disabled={cancelling} onClick={cancel}>{cancelling ? "正在取消" : "取消"}</button>
          : <button className="btn btn-ghost btn-sm" onClick={() => setShowLog(true)}>完整日志</button>}
      </div>
      {showLog && <JobLog job={job} onClose={() => setShowLog(false)} />}
    </div>
  );
}

/** 完整日志（最后 2 万字）：任务卡和“电脑”一节的任务行共用。 */
export function JobLog({ job, onClose }: { job: JobInfo; onClose: () => void }) {
  const [text, setText] = useState(job.tail);
  const [copied, setCopied] = useState(false);
  useEffect(() => {
    http.get<JobInfo>(`/api/jobs/${job.id}?tail=20000`).then((j) => setText(j.tail)).catch(() => {});
  }, [job.id]);
  const copy = async () => {
    await navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };
  return (
    <Sheet title={job.title} onClose={onClose}
      actions={<button className="btn btn-ghost" onClick={copy}>{copied ? <IconCheck size={16} /> : <IconCopy />}{copied ? "已复制" : "复制日志"}</button>}>
      <p className="blk-job-sheet-meta">{jobStateLabel(job)} · {jobDuration(job.elapsed)}</p>
      <pre className="blk-job-full">{text.trim() ? text.replace(/\s+$/, "") : "（没有输出）"}</pre>
    </Sheet>
  );
}
