import type { ConversationStatus } from "../../lib/types";

/** v2.91 §N 对话状态的字（= App ConversationStatus.label）。v3.5.2 起项目目录行尾只写这几个小字（状态胶囊随项目切换栏一起删了）。 */
export const STATUS_LABEL: Record<ConversationStatus, string> = { running: "进行中", waiting: "等你回复", done: "已完成" };
