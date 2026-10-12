import type { Message } from "./types";

/** 回复怎么结束的（与 App models/reply_end.dart 同文案）：stopped 用户停止 / interrupted 服务器重启打断（v1.52）/
 *  wrapped 步数预算用完收尾 / looped 原地打转被叫停（v1.56）。正常说完（没有 status）→ null。 */
export function endLabel(m: Pick<Message, "status">): string | null {
  switch (m.status) {
    case "stopped": return "已停止";
    case "interrupted": return "服务器重启，回答被打断";
    case "wrapped": return "步数用完，先停在这里";
    case "looped": return "原地打转，先停下了";
    default: return null;
  }
}

/** 事没做完：最后一条给“继续”（发出去就是一句普通的“继续”，服务器在下一轮历史里附说明）。 */
export function continuable(m: Pick<Message, "status">): boolean {
  return endLabel(m) !== null;
}

/** 不是用户自己停的：图标用警示色。 */
export function endWarns(m: Pick<Message, "status">): boolean {
  return m.status === "interrupted" || m.status === "looped";
}

/** “继续”的读屏说明。 */
export function continueHint(m: Pick<Message, "status">): string {
  return m.status === "looped" ? "让助手换个做法接着做" : "让助手从停下的地方接着做";
}

export const CONTINUE_TEXT = "继续";
