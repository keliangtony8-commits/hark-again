// 模型调用重试提示（v1.50，WS turn.retry，backend/app/llm_retry.py）：与 App models/retry_notice.dart 同一套规则。
// 只挂在生成中的占位消息上：普通重试在新的文字 / 思考 / 工具进度一到就收起；换了备用模型的提示留到这一轮结束。
import type { ServerEvent } from "./types";

export type RetryNotice = { attempt: number; max: number; delay_ms: number; reason: string; code?: string; fallback?: string | null; fallback_label?: string | null };

/** 这些事件说明模型又开始产出了（block.update 不算——撤回半截文字用的就是它，紧挨在 turn.retry 前面）。 */
export const RETRY_CLEARS_ON = new Set<ServerEvent["type"]>(["block.start", "block.delta", "thinking.delta", "tool.status"]);

const num = (v: unknown) => (typeof v === "number" && Number.isFinite(v) ? Math.trunc(v) : 0);

/** 字段缺失 / 类型不对时给保守值。 */
export function retryNotice(e: Record<string, unknown>): RetryNotice {
  const reason = typeof e.reason === "string" && e.reason.trim() ? e.reason.trim() : "模型调用失败";
  const fb = typeof e.fallback === "string" && e.fallback ? e.fallback : null;
  const label = typeof e.fallback_label === "string" && e.fallback_label ? e.fallback_label : null;
  return { attempt: num(e.attempt), max: num(e.max), delay_ms: num(e.delay_ms), reason, code: typeof e.code === "string" ? e.code : "", fallback: fb, fallback_label: label };
}

/** 新提示落到占位消息上：已经换过备用模型的，之后的普通重试保留“改用了哪个模型”。 */
export function mergeRetry(prev: RetryNotice | undefined, next: RetryNotice): RetryNotice {
  return prev?.fallback && !next.fallback ? { ...next, fallback: prev.fallback, fallback_label: prev.fallback_label } : next;
}

export function retryText(n: RetryNotice): string {
  if (n.fallback) return `刚才${n.reason}，这一轮改用「${n.fallback_label || n.fallback}」`;
  return `${n.reason}，正在重试${n.max > 0 && n.attempt > 0 ? ` ${n.attempt}/${n.max}` : ""}`;
}

export function retryLabel(n: RetryNotice): string {
  return n.fallback ? retryText(n) : `${retryText(n)}，不用操作，会自动接着回答`;
}
