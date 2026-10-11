/** 极简 cron 工具：只覆盖 UI 展示需要的“分 时 日 月 周”常见写法。真正调度在后端。 */
const WEEK = ["周日", "周一", "周二", "周三", "周四", "周五", "周六"];
const pad = (n: string) => n.padStart(2, "0");

export function describeCron(cron: string): string {
  const [m, h, dom, , dow] = cron.trim().split(/\s+/);
  if (!m || !h) return cron;
  const time = /^\d+$/.test(h) && /^\d+$/.test(m) ? `${pad(h)}:${pad(m)}` : null;
  if (!time) return cron;
  if (dow === "1-5") return `工作日 ${time}`;
  if (dow && /^\d$/.test(dow)) return `每${WEEK[+dow]} ${time}`;
  if (dom && /^\d+$/.test(dom)) return `每月 ${dom} 日 ${time}`;
  return `每天 ${time}`;
}

/** 这条 cron 今天（now 所在的本地日）会不会跑、几点跑：只认固定“分 时”（每小时这类不算“今天的一件事”）。
 * 与 App core/cron.dart cronTodayAt 同规则。 */
export function cronTodayAt(cron: string, now = new Date()): Date | null {
  const f = cron.trim().split(/\s+/);
  if (f.length < 5) return null;
  const [m, h, dom, , dow] = f;
  const num = /^\d+$/;
  if (!num.test(m) || !num.test(h)) return null;
  const wd = now.getDay();
  if (dow !== "*") {
    const ok = dow === "1-5" ? wd >= 1 && wd <= 5 : dow.split(",").some((d) => num.test(d) && +d % 7 === wd);
    if (!ok) return null;
  }
  if (dom !== "*" && (!num.test(dom) || +dom !== now.getDate())) return null;
  return new Date(now.getFullYear(), now.getMonth(), now.getDate(), +h, +m);
}

export const CRON_PRESETS = [
  { label: "每天 08:00", cron: "0 8 * * *" },
  { label: "工作日 09:00", cron: "0 9 * * 1-5" },
  { label: "每周一 10:00", cron: "0 10 * * 1" },
  { label: "每晚 21:00", cron: "0 21 * * *" },
];
