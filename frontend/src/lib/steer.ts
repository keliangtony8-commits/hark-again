import { initNoteOf } from "./slash";
/**
 * 回答途中补充（v1.83，服务器 steering.py；对应 App models/message.dart 的 steer / beforePending）。
 * 生成中再发纯文字 = 补充给正在进行的这一轮：user.message 带 steer + client_id；气泡插在生成中那条前面，
 * 和服务器落库的顺序（提问 → 补充 → 回复）一致。服务器收下回 turn.steered；插不进就排成下一轮（message.start 带回 client_id）。
 */
import type { Message } from "./types";

export const STEER_STATUS = "steer";
export const STEER_LABEL = "回答途中补充";
export const STEER_HINT = "补充或纠正，会并进这次回答";

/** 用户消息：途中补充进那一轮的（本机乐观气泡也标 status=steer）。 */
export const isSteer = (m: Message) => m.role === "user" && m.status === STEER_STATUS;

/** 把 m 放到生成中的那条前面（没有生成中的就接在末尾）。 */
export function beforePending(ms: Message[], m: Message): Message[] {
  const i = ms.map((x) => !!x.pending).lastIndexOf(true);
  return i < 0 ? [...ms, m] : [...ms.slice(0, i), m, ...ms.slice(i)];
}

/** 输入框里这段能不能作为补充发出：纯文字、不是 !命令 / /init、没带附件、不在编辑。 */
export const steerable = (text: string, opts: { files: number; shell: boolean; editing: boolean }) =>
  !!text.trim() && opts.files === 0 && !opts.shell && !opts.editing && initNoteOf(text) === null;
