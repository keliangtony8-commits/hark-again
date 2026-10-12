import type { PlanReviewBlock } from "./types";

/** 方案卡（v1.71 计划模式，后端 app/plan_mode.py）的显示规则，与 App models/plan_review.dart 一一对应。 */
export const PLAN_REVIEW_LONG_LINES = 14;
export const PLAN_REVIEW_LONG_CHARS = 700;

export const planReviewLabel = (b: PlanReviewBlock): string =>
  ({ approved: "已批准", rejected: "要改", expired: "已过期", pending: "等你批准" })[b.state] ?? "等你批准";

export const planReviewHint = (b: PlanReviewBlock): string =>
  ({
    approved: "已退出计划模式，按这个方案做",
    rejected: "仍在计划模式，在输入框里说要改哪里",
    expired: "这一轮停了，没等到你的答复",
    pending: "计划模式 · 批准后它才开始动手",
  })[b.state] ?? "";

/** 卡头已经显示标题：正文去掉开头那行与标题相同的 “# 标题”。 */
export function planReviewBody(b: PlanReviewBlock): string {
  const lines = b.plan.trim().split("\n");
  const first = lines[0] ?? "";
  if (/^#\s+/.test(first) && first.replace(/^#\s+/, "").trim() === b.title.trim()) return lines.slice(1).join("\n").trim();
  return b.plan.trim();
}

export function planReviewLong(b: PlanReviewBlock): boolean {
  const body = planReviewBody(b);
  return body.split("\n").length > PLAN_REVIEW_LONG_LINES || body.length > PLAN_REVIEW_LONG_CHARS;
}

export const planReviewCollapsedByDefault = (b: PlanReviewBlock) => b.state !== "pending";

export const planReviewSemantics = (b: PlanReviewBlock) => `方案：${b.title}，${planReviewLabel(b)}。${planReviewHint(b)}`;

export const PLAN_MODE_ON = "计划模式已开：只看不改，先交方案给你批准。点按关闭";
export const PLAN_MODE_OFF = "计划模式已关。点按打开：先出方案、你批准后再动手";
