import { createContext, useContext } from "react";

/** 卡片里可交互按钮的出口。聊天屏提供实现；Home 等只读场景不提供，按钮自动隐藏。 */
export type BlockActions = { replyApproval?: (id: string, approved: boolean) => void };
export const BlockActionsContext = createContext<BlockActions>({});
export const useBlockActions = () => useContext(BlockActionsContext);
