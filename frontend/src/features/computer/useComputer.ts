import { useEffect } from "react";
import { useSwr } from "../../hooks/useSwr";
import { COMPUTER_POLL_MS, type ComputerStatus, computerBusy, computerPath } from "../../lib/computer";

/** 一台电脑的状态（= App computerProvider）：电脑页上状态 / 程序 / 磁盘几节和项目首屏的“电脑”一节读同一份缓存（useSwr，键 = 路径）。
 *  undefined = 第一次加载中，null = 拿不到（且没有旧数据）。有后台任务或常驻服务（或 pollAlways 且运行中）时每 5 秒静默刷新，页面隐藏时不问。 */
export type ComputerCtl = { s: ComputerStatus | null | undefined; set: (v: ComputerStatus) => void; load: () => Promise<void> };

export function useComputer(ws: string, pollAlways = false): ComputerCtl {
  const { data, error, reload, mutate } = useSwr<ComputerStatus>(computerPath(ws));
  const s = data ?? (error ? null : undefined);
  const poll = !!s && (computerBusy(s) || (pollAlways && s.sandbox.state === "running"));
  useEffect(() => {
    if (!poll) return;
    const id = setInterval(() => { if (!document.hidden) void reload(); }, COMPUTER_POLL_MS);
    return () => clearInterval(id);
  }, [poll, reload]);
  return { s, set: mutate, load: reload };
}
