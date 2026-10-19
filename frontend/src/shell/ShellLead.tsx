import { createContext, useContext, type ReactNode } from "react";
import { createPortal } from "react-dom";

/** 顶栏左侧的上下文按钮归页面所有（主页 = 新面板，聊天 = 历史，项目 = 新建）：
 *  每层页面（AppShell ShellView）带一个槽，摆在顶栏左格的位置；页面用 <ShellLead> 把按钮“传送”进去。页面卸载，按钮跟着消失；
 *  进出“我的”横滑时按钮跟本页一起滑（v3.5.5）。和 App shell/shell_page.dart 同义。 */
export const ShellLeadSlot = createContext<HTMLElement | null>(null);

export function ShellLead({ children }: { children: ReactNode }) {
  const slot = useContext(ShellLeadSlot);
  return slot ? createPortal(children, slot) : null;
}
