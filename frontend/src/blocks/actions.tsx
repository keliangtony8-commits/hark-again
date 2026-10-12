import { createContext, useContext } from "react";

/** 卡片里可交互按钮的出口。聊天屏提供实现；Home 等只读场景不提供，按钮自动隐藏。 */
/** replyForm：values = null 表示取消；返回 false = 没发出去（断线），卡片保留输入。 */
export type BlockActions = {
  /** option = 卡上选的批准范围（主机命令卡：once / session / rule，v1.49）。 */
  replyApproval?: (id: string, approved: boolean, option?: string) => void;
  replyForm?: (id: string, values: Record<string, string> | null, remember: boolean) => boolean;
  /** 后台任务卡看着任务结束、服务器也接着说完了：重新拿一次这段对话，把助手的结论显示出来。 */
  onJobSettled?: () => void;
  /** 改动卡的整轮撤销（v1.68）：返回 null = 成功（消息已换成服务器版本），否则是给用户看的原因。 */
  undoChanges?: (token: string) => Promise<string | null>;
};
export const BlockActionsContext = createContext<BlockActions>({});
export const useBlockActions = () => useContext(BlockActionsContext);
