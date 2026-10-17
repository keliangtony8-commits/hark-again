// v2.17 移除的面板可以找回（规则在 backend app/panel_trash.py：30 天内，找回后做法都在、马上重新取数据）。
// 客户端唯一入口：removedPanels 过滤（只认服务端的 revivable）；v3.5.1 起找回在新建面板模式的胶囊里（newPanel.tsx），
// 主页上不再单独占一行。移除本身可找回，所以 HomeScreen 的“移除”不再弹危险确认。App 端 features/home/removed_panels.dart 同规则。
import { http } from "../../lib/api";
import type { HomeCard } from "../../lib/types";

/** 还能找回的面板，最近移除的在前。 */
export function removedPanels(cards: HomeCard[]): HomeCard[] {
  return cards.filter((c) => c.kind === "panel" && c.revivable)
    .sort((a, b) => (b.removed_at ?? "").localeCompare(a.removed_at ?? ""));
}

export const removePanel = (c: HomeCard) => http.post(`/api/cards/${c.id}/remove`, {});
export const revivePanel = (c: HomeCard) => http.post(`/api/cards/${c.id}/revive`, {});
