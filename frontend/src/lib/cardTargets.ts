// Home 卡片的去处（HomeCard.target）→ 按钮。和 App 的 features/home/action_card.dart cardTargets 同一张表（规则见后端 app/card_targets.py）。
// 值 = 名字 或 名字:id。route 里的 {task} 换成卡上的 task_id（任务失败提醒 → 那个任务的详情），{id} 换成冒号后的 id
// （project:<id> → 那个项目）；缺了就连同前面的 / 去掉，退到列表页。图标与“我的”页入口一致。
// 新增去处只在这里加一行；不认识的名字返回 undefined（老网页遇到新服务端不出错）。
import type { ComponentType } from "react";
import type { HomeCard } from "./types";
import { IconBrain, IconClock, IconFolder, IconGauge, IconLayout, IconPlug, IconSpark } from "../ui/icons";

export type CardTarget = { label: string; route: string; Icon: ComponentType<{ size?: number }> };

const TARGETS: Record<string, CardTarget> = {
  usage: { label: "查看用量", route: "/me/usage", Icon: IconGauge },
  tasks: { label: "查看任务", route: "/me/tasks/{task}", Icon: IconClock },
  memory: { label: "打开记忆", route: "/me/memory", Icon: IconBrain },
  skills: { label: "打开技能", route: "/me/skills", Icon: IconSpark },
  connectors: { label: "去连接的账号", route: "/me/connectors", Icon: IconPlug },
  pages: { label: "查看网页", route: "/me/pages", Icon: IconLayout },
  project: { label: "打开项目", route: "/projects/{id}", Icon: IconFolder },
};

/** "project:abc" → ["project", "abc"]；"usage" → ["usage", null]。 */
export function splitTarget(value: string): [string, string | null] {
  const i = value.indexOf(":");
  if (i < 0) return [value, null];
  const arg = value.slice(i + 1).trim();
  return [value.slice(0, i), arg || null];
}

export const cardTarget = (id: string | null | undefined): CardTarget | undefined => (id ? TARGETS[splitTarget(id)[0]] : undefined);

export function cardRoute(t: CardTarget, card: Pick<HomeCard, "task_id" | "target">): string {
  const slots: Record<string, string | null> = { task: card.task_id, id: card.target ? splitTarget(card.target)[1] : null };
  let route = t.route;
  for (const [name, v] of Object.entries(slots)) {
    route = v == null ? route.replace(`/{${name}}`, "") : route.replace(`{${name}}`, encodeURIComponent(v));
  }
  return route;
}

/** 标题上方那行小字（App cardEyebrow 同规则）：已开始 → 已交给助手；助手提议且能替你做 → 可以替你做；
 *  没有指令只有去处（助手提议或系统提醒，如“连接已失效”）→ 需要你亲自处理；其余（普通系统提醒）没有。 */
export function cardEyebrow(card: Pick<HomeCard, "origin" | "action_prompt" | "conversation_id">, target: CardTarget | undefined): string | null {
  const offered = card.origin === "agent";
  if (offered && card.conversation_id) return "已交给助手 · 查看进展";
  if (!card.action_prompt) return target ? "需要你亲自处理" : null;
  return offered ? "可以替你做" : null;
}
