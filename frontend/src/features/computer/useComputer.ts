import { useCallback, useEffect, useState } from "react";
import { http } from "../../lib/api";
import { COMPUTER_POLL_MS, type ComputerStatus, computerPath } from "../../lib/computer";

/** 一台电脑的状态（= App computerProvider）：电脑页上状态 / 程序 / 磁盘几节共用一份，项目首屏的“电脑”一节自己用一份。
 *  undefined = 加载中，null = 拿不到。有后台任务在跑（或 pollAlways 且运行中）时每 5 秒静默刷新，页面隐藏时不问。 */
export type ComputerCtl = { s: ComputerStatus | null | undefined; set: (v: ComputerStatus) => void; load: (silent?: boolean) => Promise<void> };

export function useComputer(ws: string, pollAlways = false): ComputerCtl {
  const [s, setS] = useState<ComputerStatus | null | undefined>(undefined);
  const load = useCallback((silent = false) => http.get<ComputerStatus>(computerPath(ws))
    .then((v) => setS(v))
    .catch(() => { if (!silent) setS(null); }), [ws]);
  useEffect(() => { void load(); }, [load]);
  const poll = !!s && (s.running_jobs.length > 0 || (pollAlways && s.sandbox.state === "running"));
  useEffect(() => {
    if (!poll) return;
    const id = setInterval(() => { if (!document.hidden) void load(true); }, COMPUTER_POLL_MS);
    return () => clearInterval(id);
  }, [poll, load]);
  return { s, set: setS, load };
}
