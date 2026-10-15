import type { ConversationStatus } from "../../lib/types";

/** v2.91 §N 状态胶囊的字（= App ConversationStatus.label）。 */
export const STATUS_LABEL: Record<ConversationStatus, string> = { running: "进行中", waiting: "等你回复", done: "已完成" };

/** 对话状态胶囊（项目列表、项目切换栏共用，v2.95 项目状态 = 那段对话的状态；= App features/chat/status_capsule.dart）。值只来自服务器 status，这里只管样子：
 *  进行中 = 安静底 + 呼吸小点；等你回复 = 墨色实心（唯一要你动手的信号）；已完成 = 安静底、三级字。状态变了 key 变 → 淡入换字。 */
export default function StatusCapsule({ status }: { status: ConversationStatus }) {
  return (
    <span key={status} className={`status-capsule ${status}`} title={`状态：${STATUS_LABEL[status]}`}>
      {status === "running" && <span className="status-dot" aria-hidden />}
      {STATUS_LABEL[status]}
    </span>
  );
}
