// v2.17 移除的面板可以找回（规则在 backend app/panel_trash.py：30 天内，找回后做法都在、马上重新取数据）。
// 客户端唯一入口：removedPanels 过滤（只认服务端的 revivable）、RemovedRow“面板”段末一行“N 个最近移除的面板”，
// 展开后每个可“放回”。移除本身可找回，所以 HomeScreen 的“移除”不再弹危险确认。App 端 features/home/removed_panels.dart 同规则。
import { useState } from "react";
import { http } from "../../lib/api";
import { formatWhen } from "../../lib/format";
import type { HomeCard } from "../../lib/types";
import { IconChevron, IconHistory } from "../../ui/icons";

/** 还能找回的面板，最近移除的在前。 */
export function removedPanels(cards: HomeCard[]): HomeCard[] {
  return cards.filter((c) => c.kind === "panel" && c.revivable)
    .sort((a, b) => (b.removed_at ?? "").localeCompare(a.removed_at ?? ""));
}

export const removePanel = (c: HomeCard) => http.post(`/api/cards/${c.id}/remove`, {});
export const revivePanel = (c: HomeCard) => http.post(`/api/cards/${c.id}/revive`, {});

export function RemovedRow({ cards, onRevive }: { cards: HomeCard[]; onRevive: (c: HomeCard) => void }) {
  const [open, setOpen] = useState(false);
  if (cards.length === 0) return null;
  return (
    <div className={`snoozed enter ${open ? "open" : ""}`}>
      <button className="snoozed-head" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        <IconHistory size={16} />
        <span>{cards.length} 个最近移除的面板 · 30 天内可找回</span>
        <IconChevron />
      </button>
      {open && (
        <div className="snoozed-list">
          {cards.map((c) => (
            <div key={c.id} className="snoozed-item">
              <span className="snoozed-title">{c.title}</span>
              <span className="snoozed-time">移除于 {formatWhen(c.removed_at!)}</span>
              <button className="btn btn-ghost btn-sm" onClick={() => onRevive(c)}>放回</button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
