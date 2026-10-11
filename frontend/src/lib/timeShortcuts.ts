// 常用的“稍后某个时刻”：一次性任务的计划（features/me/SchedulePicker.tsx）和 Home 卡片的稍后提醒（features/home/Snooze.tsx）共用。
// 与 App models/time_shortcuts.dart 同规则。
/** 一次性的快捷时刻：1 小时后（取整到 5 分）/ 今晚 20:00（已过就不给）/ 明早 08:00 / 明晚 20:00。 */
export function onceShortcuts(now = new Date()): { label: string; at: Date }[] {
  const h = new Date(now.getTime() + 3_600_000);
  const at = (dayOffset: number, hour: number) => new Date(now.getFullYear(), now.getMonth(), now.getDate() + dayOffset, hour);
  const tonight = at(0, 20);
  return [
    { label: "1 小时后", at: new Date(h.getFullYear(), h.getMonth(), h.getDate(), h.getHours(), (Math.floor(h.getMinutes() / 5) + 1) * 5) },
    ...(tonight.getTime() > now.getTime() + 600_000 ? [{ label: "今晚 20:00", at: tonight }] : []),
    { label: "明早 08:00", at: at(1, 8) },
    { label: "明晚 20:00", at: at(1, 20) },
  ];
}
