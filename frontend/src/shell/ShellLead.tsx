import { createContext, useContext, type ReactNode } from "react";
import { createPortal } from "react-dom";

/** 顶栏左侧的上下文按钮归页面所有（主页 = 新面板，聊天 = 历史，项目 = 新建）：
 *  外壳只留一个空槽，页面用 <ShellLead> 把按钮“传送”进去。页面卸载，按钮跟着消失。和 App shell/shell_page.dart 同义。 */
export const ShellLeadSlot = createContext<HTMLElement | null>(null);

export function ShellLead({ children }: { children: ReactNode }) {
  const slot = useContext(ShellLeadSlot);
  return slot ? createPortal(children, slot) : null;
}
