// 工作区的“电脑”（服务器 app/computer.py；App models/computer.dart 同一套规则）：状态词、说明行、内存比例、行尾小字、重启说明；
// v1.27 CPU、内存打满警示、程序行、磁盘拆分、清理、装过的工具；v1.82 常驻服务健康。
import { formatSize } from "./files";
import type { ListeningPort } from "./preview";
import { jobDisk, jobDiskGroupName, jobDuration, jobUsage, jobUsageLabel } from "./jobs";
import { formatAgo } from "./format";
import type { JobDisk, JobInfo } from "./types";

export type ComputerState = "running" | "stopped" | "none" | "unreachable";
export type ComputerStopReason = "idle" | "room";
export type ComputerStatus = {
  workspace: string; name: string;
  sandbox: { state: ComputerState; memory_used?: number | null; memory_limit?: number | null; started_at?: string | null;
    last_used_at?: string | null; idle_minutes?: number | null; outdated?: boolean;
    // v1.74 休眠原因：idle 空闲太久 / room 给其它工作区腾内存（只在 stopped 且是服务器停的时有）
    stopped_by?: ComputerStopReason | null; stopped_at?: string | null;
    cpu_percent?: number | null; oom_kills?: number; processes?: ComputerProcess[] };
  disk_used: number; disk_partial: boolean; running_jobs: JobInfo[];
  services?: ServiceInfo[]; // v1.82 常驻服务（服务器 app/services.py）：在跑的 + 最近 24 小时意外结束的
  storage?: ComputerStorage; tools?: InstalledTool[];
  ports?: ListeningPort[]; // v1.30 在监听的端口（只在运行中时有）
  // v1.31 磁盘配额（服务器 app/quota.py）：上限字节（null = 不限）；ok / tight ≥85% / full 满了（新文件写不进、后台任务会被停）/ off
  disk_limit?: number | null; disk_level?: DiskLevel;
  memory?: MemoryView | null; // v1.94 内存去哪了（服务器 app/memory_view.py，只在运行中有）
  disk_jobs?: (JobInfo & { log_kept?: boolean })[]; // v1.98 最近 7 天谁写得最多（服务器 job_disk.leaders，不用开机）
  machine?: MachineInfo | null; // v2.85 整台服务器（服务器 app/machine.py）：只在个人工作区有
};
/** 整台服务器（v2.85）：字节；读不到的为 null。 */
export type MachineInfo = { cpus: number | null; load1: number | null; memory_total: number | null; memory_used: number | null;
  disk_total: number | null; disk_used: number | null };
export type DiskLevel = "ok" | "tight" | "full" | "off";
/** 常驻服务的健康：up 在跑 / restarting 进程退出了、等自动重启 / gave_up 已停止自动重启（或别的意外结束）。 */
export type ServiceHealth = "up" | "restarting" | "gave_up";
export type ServiceInfo = JobInfo & { health: ServiceHealth; ports: number[]; uptime: number | null;
  earlier_stops?: number }; // v2.85 同名同命令的旧停止记录合进这一行（服务器 services.merge）
export type ComputerProcess = { pid: number; cpu: number; memory: number; elapsed: number; command: string };
export type ComputerStorage = { files: number; installed: number; logs: number; spill: number; cache: number; cleanable: number };
export type InstalledTool = { kind: "pip" | "npm" | string; name: string; version: string };
export type CleanupResult = { freed: number; status: ComputerStatus };

export const COMPUTER_POLL_MS = 5000;     // 有后台任务在跑时多久刷新一次（每次要问 Docker，别太密）
export const COMPUTER_POLL_IDLE_MS = 10_000; // v3.5.1 只有常驻服务、没有普通后台任务时放慢一半（= App Timing.computerPollIdle）
export const COMPUTER_MEMORY_TIGHT = 0.85; // 内存吃到多少算紧张

export const computerPath = (ws: string) => `/api/projects/${ws}/computer`;

export function computerStateLabel(s: ComputerState): string {
  switch (s) {
    case "running": return "运行中";
    case "stopped": return "休眠中";
    case "none": return "还没开机";
    default: return "无法连接沙盒";
  }
}

export function computerMemoryRatio(c: ComputerStatus): number | null {
  const { state, memory_used: u, memory_limit: l } = c.sandbox;
  if (state !== "running" || u == null || l == null || l <= 0) return null;
  return Math.min(1, Math.max(0, u / l));
}

export function computerDetail(c: ComputerStatus): string {
  const disk = `文件 ${formatSize(c.disk_used)}${c.disk_partial ? "+" : ""}${c.disk_limit != null ? ` / ${formatSize(c.disk_limit)}` : ""}`;
  const sb = c.sandbox;
  switch (sb.state) {
    case "running":
      return [sb.cpu_percent != null ? `CPU ${Math.round(sb.cpu_percent)}%` : "", sb.memory_used != null ? `内存 ${formatSize(sb.memory_used)}${sb.memory_limit != null ? ` / ${formatSize(sb.memory_limit)}` : ""}` : "", disk]
        .filter(Boolean).join(" · ");
    case "stopped": return `${sleepReason(c)}用到时自动开机 · ${disk}`;
    case "none": return `首次运行命令时启动 · ${disk}`;
    default: return `沙盒服务未运行，命令和后台任务暂不可用 · ${disk}`;
  }
}

function sleepReason(c: ComputerStatus): string {
  const sb = c.sandbox;
  if (sb.stopped_by === "room") return "给正在用的其它工作区腾内存，先休眠了，";
  return sb.idle_minutes != null ? `空闲 ${sb.idle_minutes} 分钟自动休眠，` : "";
}

export const liveServices = (c: ComputerStatus) => (c.services ?? []).filter((v) => v.health !== "gave_up").length;
export const deadServices = (c: ComputerStatus) => (c.services ?? []).length - liveServices(c);
/** 状态会自己变（有任务在跑、服务在跑或等重启）：该轮询。 */
export const computerBusy = (c: ComputerStatus) => c.running_jobs.length > 0 || liveServices(c) > 0;
export const computerHintWarn = (c: ComputerStatus) => diskFull(c) || deadServices(c) > 0;

export function computerHint(c: ComputerStatus): string | null {
  if (diskFull(c)) return "磁盘已满";
  if (deadServices(c)) return `${deadServices(c)} 个服务停了`;
  if (c.running_jobs.length) return `${c.running_jobs.length} 个任务运行中`;
  if (liveServices(c)) return `${liveServices(c)} 个服务运行中`;
  if (c.sandbox.outdated && c.sandbox.state !== "unreachable") return "下次用到时更新";
  return c.sandbox.state === "running" ? "空闲" : null;
}

export const diskFull = (c: ComputerStatus) => c.disk_level === "full";
export const diskTight = (c: ComputerStatus) => c.disk_level === "tight" || diskFull(c);

/** 磁盘占上限的比例（0–1）；不限 → null（不画条）。 */
export function computerDiskRatio(c: ComputerStatus): number | null {
  const l = c.disk_limit;
  if (l == null || l <= 0) return null;
  return Math.min(1, Math.max(0, c.disk_used / l));
}

export const computerDiskLine = (c: ComputerStatus) =>
  `已用 ${formatSize(c.disk_used)}${c.disk_partial ? "+" : ""}，上限 ${formatSize(c.disk_limit ?? 0)}`;

export function computerDiskNote(c: ComputerStatus): string | null {
  switch (c.disk_level) {
    case "full": return "已满：无法写入新文件，后台任务将被停止。请清理空间或删除不需要的文件";
    case "tight": return "空间紧张：写满后将无法写入新文件，后台任务也会停止";
    default: return null;
  }
}

export const computerRestartText = (c: ComputerStatus) =>
  (c.running_jobs.length ? `将停止 ${c.running_jobs.length} 个正在运行的后台任务。` : "")
  + (liveServices(c) ? `${liveServices(c)} 个常驻服务会马上重新拉起。` : "") + "文件和装过的软件都在，下次用到时自动开机。";

export const computerSemantics = (c: ComputerStatus) =>
  `电脑${computerStateLabel(c.sandbox.state)}，${computerDetail(c)}${c.running_jobs.length ? `，${c.running_jobs.length} 个后台任务运行中` : ""}`
  + `${liveServices(c) ? `，${liveServices(c)} 个常驻服务` : ""}${deadServices(c) ? `，${deadServices(c)} 个服务停了` : ""}`;

/** 服务行的副标题（= App serviceLine）：在跑 → 运行多久 · 端口 · 重启过几次；等重启 → 几秒后重启 · 上次退出码；停了 → 原因。 */
export function serviceLine(v: ServiceInfo, now = Date.now()): string {
  const restarted = (v.restarts ?? 0) > 0 ? `已重启 ${v.restarts} 次` : "";
  switch (v.health) {
    case "up":
    {
      const u = jobUsage(v.usage);
      return [`运行 ${jobDuration(v.uptime ?? v.elapsed)}`, v.ports.length ? `端口 ${v.ports.join("、")}` : "", u ? jobUsageLabel(u) : "", restarted,
        v.earlier_stops ? `24 小时内停过 ${v.earlier_stops} 次` : ""].filter(Boolean).join(" · ");
    }
    case "restarting": {
      const s = v.restart_at ? Math.floor((Date.parse(v.restart_at) - now) / 1000) : 0;
      return [s <= 1 ? "马上重启" : `${jobDuration(s)}后重启`, v.exit_code != null ? `上次退出码 ${v.exit_code}` : "", restarted].filter(Boolean).join(" · ");
    }
    default:
      return v.stop_reason || `意外退出${v.exit_code != null ? `（退出码 ${v.exit_code}）` : ""}`;
  }
}

export const serviceAction = (h: ServiceHealth) => (h === "up" ? "重启" : h === "restarting" ? "立即重启" : "重新启动");

export const serviceSemantics = (v: ServiceInfo) =>
  `常驻服务 ${v.title}，${v.health === "up" ? "运行中" : v.health === "restarting" ? "等待自动重启" : "已停止"}，${serviceLine(v)}`;

export function computerOomNote(c: ComputerStatus): string | null {
  const n = c.sandbox.oom_kills ?? 0;
  if (c.sandbox.state !== "running" || n <= 0) return null;
  const cap = c.sandbox.memory_limit != null ? `（上限 ${formatSize(c.sandbox.memory_limit)}）` : "";
  return `内存不够，系统强制结束过 ${n} 个程序${cap}。分批处理或重启能缓过来`;
}

export const processTitle = (p: ComputerProcess) => commandTitle(p.command);

/** 命令去掉开头程序的路径：“/usr/bin/python3 a.py” → “python3 a.py”。 */
export function commandTitle(command: string): string {
  const c = command.trim();
  const sp = c.indexOf(" ");
  const head = sp < 0 ? c : c.slice(0, sp);
  return (head.split("/").pop() ?? head) + (sp < 0 ? "" : c.slice(sp));
}

export const processLine = (p: ComputerProcess) =>
  `CPU ${Math.round(p.cpu)}% · 内存 ${formatSize(p.memory)} · 运行 ${jobDuration(p.elapsed)}`;

export const EMPTY_STORAGE: ComputerStorage = { files: 0, installed: 0, logs: 0, spill: 0, cache: 0, cleanable: 0 };

export type StorageKey = "files" | "installed" | "logs" | "spill" | "cache";
export function storageRows(st: ComputerStorage): [StorageKey, string, string, number][] {
  const rows: [StorageKey, string, string, number][] = [
    ["files", "文件", "你和我放进来的", st.files],
    ["installed", "装的软件", "pip / npm 装进 ~/.local 的", st.installed],
    ["logs", "任务日志", "后台任务的完整输出", st.logs],
    ["spill", "长输出存档", "太长没塞进对话的命令输出", st.spill],
    ["cache", "下载缓存", "pip / npm 的缓存", st.cache],
  ];
  return rows.filter(([k, , , n]) => k === "files" || n > 0);
}

export const cleanupLabel = (st: ComputerStorage) => (st.cleanable > 0 ? `清理 ${formatSize(st.cleanable)}` : null);
export const CLEANUP_TEXT = "删除长输出存档、已结束任务的完整日志和下载缓存。文件、已安装软件和运行中的任务不受影响；聊天中的任务卡仍可查看结论。";
export const cleanupDone = (freed: number) => (freed > 0 ? `腾出了 ${formatSize(freed)}` : "没有可清理的了");

export function toolsSummary(tools: InstalledTool[]): string {
  if (!tools.length) return "还没装过，用到时我会 pip / npm 装进来";
  const pip = tools.filter((t) => t.kind === "pip").length, npm = tools.length - pip;
  return [pip ? `pip ${pip} 个` : "", npm ? `npm ${npm} 个` : ""].filter(Boolean).join(" · ");
}

// ---- v1.94 内存去哪了（= App models/computer.dart 同名规则）----
export type MemoryOwner = "job" | "service" | "process";
export type MemoryRow = { kind: MemoryOwner; title: string; memory: number; processes: number; share: number; id?: string; pid?: number };
export type MemoryView = { used: number; limit: number | null; rows: MemoryRow[]; other: number };

const clamp01 = (n: number) => Math.min(1, Math.max(0, n || 0));
export const memoryRowKey = (r: MemoryRow) => r.id ?? `pid-${r.pid}`;
export const memoryRatio = (v: MemoryView) => (v.limit && v.limit > 0 ? clamp01(v.used / v.limit) : null);
/** 和状态块的内存条同一个门槛。 */
export const memoryTight = (v: MemoryView) => (memoryRatio(v) ?? 0) >= COMPUTER_MEMORY_TIGHT;
export const memoryOtherShare = (v: MemoryView) => (v.used > 0 ? clamp01(v.other / v.used) : 0);

/** 这一节要不要出现：电脑在跑、有谁可排。 */
export function memoryViewOf(s: ComputerStatus): MemoryView | null {
  const m = s.memory;
  return s.sandbox.state === "running" && m && (m.rows ?? []).length ? m : null;
}

export const memoryViewLine = (v: MemoryView) => `已用 ${formatSize(v.used)}${v.limit != null ? `，上限 ${formatSize(v.limit)}` : ""}`;
export const memoryRowTitle = (r: MemoryRow) => (r.kind === "job" || r.kind === "service" ? r.title : commandTitle(r.title));
export const memoryPercent = (share: number) => (share > 0 && share < 0.01 ? "不到 1%" : `${Math.round(clamp01(share) * 100)}%`);

export function memoryTightNote(v: MemoryView): string | null {
  if (!memoryTight(v)) return null;
  const top = v.rows[0];
  const who = top ? `，占用最多的是「${memoryRowTitle(top)}」（约 ${formatSize(top.memory)}），优先停止它效果最明显` : "";
  return `内存紧张：继续增长将强制结束程序（优先结束普通后台任务）${who}`;
}

export const memoryRowLine = (r: MemoryRow) => [
  r.kind === "job" ? "后台任务" : r.kind === "service" ? "常驻服务" : r.pid != null ? `程序 · PID ${r.pid}` : "程序",
  ...(r.processes > 1 ? [`${r.processes} 个进程`] : []),
  `占 ${memoryPercent(r.share)}`,
].join(" · ");

export const MEMORY_OTHER_TITLE = "其它";
export const memoryOtherLine = (v: MemoryView) => `系统和零碎小程序 · 占 ${memoryPercent(memoryOtherShare(v))}`;

// ---- v1.98 磁盘谁写得最多（服务器 app/job_disk.leaders；App models/computer.dart 同一套）----
/** 最近 7 天结束的一个任务和它结算时的磁盘账；logKept = 完整日志还在（清理能腾出那份；写下的文件是你的，不清）。 */
export type DiskJob = { job: JobInfo; disk: JobDisk; logKept: boolean; total: number };
export const DISK_JOBS_TITLE = "最近 7 天谁写得最多";
export function diskJobRows(s: ComputerStatus): DiskJob[] {
  const out: DiskJob[] = [];
  for (const j of s.disk_jobs ?? []) {
    const d = jobDisk(j.disk);
    if (!d || d.written + d.log <= 0) continue;
    const logKept = j.log_kept === true;
    const total = d.written + (logKept ? d.log : 0); // 日志清掉了就只剩写的文件
    if (total > 0) out.push({ job: j, disk: d, logKept, total });
  }
  return out.sort((a, b) => b.total - a.total);
}
export function diskJobShare(s: ComputerStatus, r: DiskJob): number {
  const rows = diskJobRows(s);
  const base = s.disk_used > 0 ? s.disk_used : rows[0]?.total ?? 0;
  return base > 0 ? clamp01(r.total / base) : 0;
}
export const diskJobLine = (r: DiskJob, now = new Date()) => [
  ...(r.job.finished_at ? [formatAgo(r.job.finished_at, now)] : []),
  ...(r.disk.top.length ? [`主要写在 ${jobDiskGroupName(r.disk.top[0].path)}`] : r.disk.written === 0 ? ["只有日志"] : []),
  ...(r.disk.log > 0 ? [r.logKept ? `日志 ${formatSize(r.disk.log)}` : "日志已清"] : []),
  ...(r.disk.overlap > 0 && r.disk.written > 0 ? ["含同时段任务"] : []),
].join(" · ");
export const diskJobSize = (r: DiskJob) => `${formatSize(r.total)}${r.disk.partial ? "+" : ""}`;
export function diskJobsNote(s: ComputerStatus): string {
  const logs = diskJobRows(s).filter((r) => r.logKept).reduce((a, r) => a + r.disk.log, 0);
  return `按任务结束时数的账；写下的文件不会被清理，要腾地方得删它们${logs > 0 ? `，日志共 ${formatSize(logs)} 可以清` : ""}`;
}

/** “整台服务器”一行的副标题（= App machineLine）：4 核（负载 0.3） · 内存 1 GB / 4 GB · 磁盘 12 GB / 40 GB；全读不到 → null。 */
export function machineLine(m: MachineInfo): string | null {
  const parts = [
    m.cpus != null ? `${m.cpus} 核${m.load1 != null ? `（负载 ${m.load1.toFixed(1)}）` : ""}` : "",
    m.memory_total != null ? `内存 ${m.memory_used != null ? `${formatSize(m.memory_used)} / ` : ""}${formatSize(m.memory_total)}` : "",
    m.disk_total != null ? `磁盘 ${m.disk_used != null ? `${formatSize(m.disk_used)} / ` : ""}${formatSize(m.disk_total)}` : "",
  ].filter(Boolean);
  return parts.length ? parts.join(" · ") : null;
}

/** 电脑页页头说明（v2.85 = App computerIntro）：先说清是服务器上隔出来的一块、各有多大，再说用途。 */
export function computerIntro(c: ComputerStatus | undefined | null, personal: boolean): string {
  const size = [c?.sandbox.memory_limit != null ? `内存 ${formatSize(c.sandbox.memory_limit)}` : "",
    c?.disk_limit != null ? `空间 ${formatSize(c.disk_limit)}` : ""].filter(Boolean).join(" · ");
  const head = `${personal ? "你的云电脑" : "这个项目的云电脑"}是服务器上隔出来的一块云端 Linux${size ? `（${size}）` : ""}`;
  return personal ? `${head}：我在这里运行代码、安装软件、执行后台任务，产物存入“我的文件”。`
    : `${head}：项目内的对话在这里运行代码、安装软件、执行后台任务，文件即项目文件。`;
}
