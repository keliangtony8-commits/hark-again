import { useEffect } from "react";
import type { TaskRun } from "../lib/types";
import { useSwr } from "./useSwr";

/** 和 App Timing.taskRunPoll 一致：有运行在排队/进行时多久刷新一次。 */
export const TASK_RUN_POLL_MS = 4000;

/** 某任务最近的运行记录（useSwr：再进任务详情先显示上次的记录）。busy（排队中或有 running）时每 TASK_RUN_POLL_MS 调 onTick（刷新任务 + 记录），都结束就停。 */
export function useTaskRuns(taskId: string, requested: boolean, onTick: () => void) {
  const { data: runs, error, reload } = useSwr<TaskRun[]>(`/api/tasks/${taskId}/runs`);

  const busy = requested || (runs ?? []).some((r) => r.status === "running");
  useEffect(() => {
    if (!busy) return;
    const t = setInterval(() => { void reload(); onTick(); }, TASK_RUN_POLL_MS);
    return () => clearInterval(t);
  }, [busy, reload, onTick]);

  return { runs: runs ?? null, error: error ? String(error) : null, reload, busy };
}
