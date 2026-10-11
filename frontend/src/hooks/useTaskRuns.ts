import { useCallback, useEffect, useState } from "react";
import { http } from "../lib/api";
import type { TaskRun } from "../lib/types";

/** 和 App Timing.taskRunPoll 一致：有运行在排队/进行时多久刷新一次。 */
export const TASK_RUN_POLL_MS = 4000;

/** 某任务最近的运行记录。busy（排队中或有 running）时每 TASK_RUN_POLL_MS 调 onTick（刷新任务 + 记录），都结束就停。 */
export function useTaskRuns(taskId: string, requested: boolean, onTick: () => void) {
  const [runs, setRuns] = useState<TaskRun[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    try { setRuns(await http.get<TaskRun[]>(`/api/tasks/${taskId}/runs`)); setError(null); }
    catch (e) { setError(String(e)); }
  }, [taskId]);

  useEffect(() => { reload(); }, [reload]);

  const busy = requested || (runs ?? []).some((r) => r.status === "running");
  useEffect(() => {
    if (!busy) return;
    const t = setInterval(() => { reload(); onTick(); }, TASK_RUN_POLL_MS);
    return () => clearInterval(t);
  }, [busy, reload, onTick]);

  return { runs, error, reload, busy };
}
