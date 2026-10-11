import { createContext, useContext } from "react";

/** 卡片里可交互按钮的出口。聊天屏提供实现；Home 等只读场景不提供，按钮自动隐藏。 */
/** replyForm：values = null 表示取消；返回 false = 没发出去（断线），卡片保留输入。 */
export type BlockActions = {
  replyApproval?: (id: string, approved: boolean) => void;
  replyForm?: (id: string, values: Record<string, string> | null, remember: boolean) => boolean;
};
export const BlockActionsContext = createContext<BlockActions>({});
export const useBlockActions = () => useContext(BlockActionsContext);
