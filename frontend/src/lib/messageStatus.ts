import type { Message } from "./types";

/** 不完整回复的说明（与 App models/message.dart cutLabel 同文案）：用户停止 / 服务器重启打断（v1.52 turn_journal）；完整 → null。 */
export function cutLabel(m: Pick<Message, "status">): string | null {
  return m.status === "stopped" ? "已停止" : m.status === "interrupted" ? "服务器重启，回答被打断" : null;
}
