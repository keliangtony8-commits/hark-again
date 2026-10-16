// 收件箱的一行报告 + 它的操作（v1.09，App features/home/report_actions.dart 同规则）：
// 点行 = 打开报告对话；行尾“更多” = 稍后再看（快捷时刻，与建议卡的稍后提醒同一张表）/ 标为已读（未读才有）/ 收起。
// 推迟后的报告由收件箱底部 SnoozedRow（noun=稍后再看）列出，可现在放回。
import { onceShortcuts } from "../../lib/timeShortcuts";
import { cardGlance } from "../../lib/reportGlance";
import type { HomeCard } from "../../lib/types";
import { IconCheck, IconClock, IconClose, IconInbox, IconMore } from "../../ui/icons";
import { ListRow, Menu, type MenuItem } from "../../ui/kit";
import type { Snooze } from "./Snooze";

export function reportMenu(r: HomeCard, on: { snooze: Snooze; read: (r: HomeCard) => void; dismiss: (r: HomeCard) => void }): MenuItem[] {
  return [
    ...onceShortcuts().map((s) => ({ label: `稍后再看 · ${s.label}`, icon: <IconClock />, onSelect: () => on.snooze(r, s.at) })),
    ...(r.unread ? [{ label: "标为已读", icon: <IconCheck />, onSelect: () => on.read(r) }] : []),
    { label: "收起", icon: <IconClose />, onSelect: () => on.dismiss(r) },
  ];
}

export function InboxRow({ card: r, time, onOpen, ...on }: {
  card: HomeCard; time: string; onOpen: (r: HomeCard) => void;
  snooze: Snooze; read: (r: HomeCard) => void; dismiss: (r: HomeCard) => void;
}) {
  return (
    <ListRow className={`report-row${r.unread ? " unread" : ""}`} onClick={() => onOpen(r)} icon={<IconInbox />} title={r.title} sub={cardGlance(r)} trail={null}
      control={<span className="row-trail">{time}<Menu label="稍后再看或收起" trigger={<IconMore />} items={reportMenu(r, on)} /></span>} />
  );
}
