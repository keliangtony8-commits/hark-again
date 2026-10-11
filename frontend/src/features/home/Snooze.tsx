// Home 卡片的“稍后提醒”（规则在 backend app/card_snooze.py；App features/home/card_snooze.dart 同规则）：
// - SnoozeMenu：建议卡标题右边的小钮 → 快捷时刻（与一次性任务同一张表 lib/timeShortcuts.ts）
// - SnoozedRow：“为你准备”/“收件箱”底部一行“N 条稍后提醒|稍后再看 · 最早 …”，展开后每条可现在放回（报告的行内菜单在 InboxRow.tsx）
// 客户端只看 snoozed_until 是否为空来藏卡，不比本机时钟。
import { useState } from "react";
import { formatWhen } from "../../lib/format";
import { onceShortcuts } from "../../lib/timeShortcuts";
import type { HomeCard } from "../../lib/types";
import { IconChevron, IconClock, IconSnooze } from "../../ui/icons";
import { Menu } from "../../ui/kit";

/** 推迟到 at；null = 现在放回。 */
export type Snooze = (card: HomeCard, at: Date | null) => void;

export function SnoozeMenu({ card, onSnooze }: { card: HomeCard; onSnooze: Snooze }) {
  return (
    <Menu label="稍后提醒" trigger={<IconSnooze size={18} />}
      items={onceShortcuts().map((s) => ({ label: s.label, icon: <IconClock />, onSelect: () => onSnooze(card, s.at) }))} />
  );
}

export function SnoozedRow({ cards, onSnooze, noun = "稍后提醒" }: { cards: HomeCard[]; onSnooze: Snooze; noun?: "稍后提醒" | "稍后再看" }) {
  const [open, setOpen] = useState(false);
  if (cards.length === 0) return null;
  const sorted = [...cards].sort((a, b) => a.snoozed_until!.localeCompare(b.snoozed_until!));
  return (
    <div className={`snoozed ${open ? "open" : ""}`}>
      <button className="snoozed-head" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        <IconSnooze size={16} />
        <span>{sorted.length} 条{noun} · 最早 {formatWhen(sorted[0].snoozed_until!)}</span>
        <IconChevron />
      </button>
      {open && (
        <div className="snoozed-list">
          {sorted.map((c) => (
            <div key={c.id} className="snoozed-item">
              <span className="snoozed-title">{c.title}</span>
              <span className="snoozed-time">{formatWhen(c.snoozed_until!)}</span>
              <button className="btn btn-ghost btn-sm" onClick={() => onSnooze(c, null)}>现在放回</button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
