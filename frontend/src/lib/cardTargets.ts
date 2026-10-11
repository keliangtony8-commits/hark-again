// Home 卡片的固定去处（HomeCard.target）→ 按钮。和 App 的 features/home/action_card.dart cardTargets 同一张表。
// route 里的 {task} 换成卡上的 task_id（任务失败提醒 → 那个任务的详情；没有 task_id 就退到列表），用 cardRoute。
// 新增去处只在这里加一行；不认识的值返回 undefined（老网页遇到新服务端不出错）。
import type { ComponentType } from "react";
import type { HomeCard } from "./types";
import { IconClock, IconGauge } from "../ui/icons";

export type CardTarget = { label: string; route: string; Icon: ComponentType<{ size?: number }> };

const TARGETS: Record<string, CardTarget> = {
  usage: { label: "查看用量", route: "/me/usage", Icon: IconGauge },
  tasks: { label: "查看任务", route: "/me/tasks/{task}", Icon: IconClock },
};

export const cardTarget = (id: string | null | undefined): CardTarget | undefined => (id ? TARGETS[id] : undefined);

export function cardRoute(t: CardTarget, card: Pick<HomeCard, "task_id">): string {
  if (!t.route.includes("/{task}")) return t.route;
  return card.task_id ? t.route.replace("{task}", card.task_id) : t.route.replace("/{task}", "");
}
