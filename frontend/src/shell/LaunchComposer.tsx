import { type ReactNode, useLayoutEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import Composer from "../features/chat/Composer";
import type { OutgoingFile } from "../lib/types";
import { IconChevronDown } from "../ui/icons";
import { stagger } from "../ui/kit";

export const STARTER_PROMPTS = ["帮我规划这周的学习", "查一下今天的新闻", "把这段话翻译成英文", "每天早上 8 点给我简报"];

/** 跳到聊天并在新对话里发出（ChatScreen 读路由状态 draft/files）。主页、项目页、页面列表都走它。 */
export function useAskInNewChat() {
  const nav = useNavigate();
  return (text: string, files: OutgoingFile[] = []) => nav("/chat", { state: { draft: text, files } });
}

/** 模式里的胶囊能做的两件事（都会先收起输入框）：ask = 把一句话（包过 wrap）发进新对话；then = 收起后做别的（打开表单、放回面板）。 */
export type LaunchActions = { ask: (text: string) => void; then: (action: () => void) => void };

/** 发起态的一种模式（= App shell/launch_composer.dart LaunchMode，同名同字段）。 */
export type LaunchMode = {
  /** 输入框正上方的一行淡色小字（“创建一个新面板”）。 */
  caption: string;
  /** 输入框占位词轮播。 */
  hints: string[];
  /** 占位词前的图标（和 hints 一一对应，Hark 样式）；模式里不出“添加附件”。 */
  hintIcons?: ReactNode[];
  /** 发出前把输入包一层（newPanelPrompt）。 */
  wrap: (text: string) => string;
  /** 建议问题那一格换成的内容（胶囊们）。 */
  extras: (go: LaunchActions) => ReactNode;
};

/** 一级页面（主页、项目列表）底部的输入胶囊：和聊天页同一个 Composer、同一位置、同一外观，发出 = 新对话。
 *  聚焦时整页磨砂变暗、胶囊左边出现“收起”、上方升起建议问题；点遮罩 / 收起 / Esc 收起。和 App shell/launch_composer.dart 同义。
 *  v3.5.1 模式（照 Hark）：外面把 mode 设成一种模式 = 进入发起态并聚焦，上方换成这个模式的胶囊 + 小字、占位词轮播、
 *  不出“添加附件”、发出前包一层（主页 + 新建面板 = features/home/newPanel.tsx newPanelMode）；收起即 onModeEnd（外面清回 null）。 */
export default function LaunchComposer({ suggestions = STARTER_PROMPTS, mode = null, onModeEnd }: {
  suggestions?: string[]; mode?: LaunchMode | null; onModeEnd?: () => void;
}) {
  const ask = useAskInNewChat();
  const [focused, setFocused] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const end = () => { setFocused(false); onModeEnd?.(); };
  const collapse = () => { (document.activeElement as HTMLElement | null)?.blur(); end(); };
  // 设模式 = 聚焦输入框（在同一次点击里同步聚焦，手机浏览器才肯弹键盘）
  const hasMode = !!mode;
  useLayoutEffect(() => { if (hasMode) box.current?.querySelector("textarea")?.focus(); }, [hasMode]);
  const active = focused ? mode : null;
  const send = (text: string, files: OutgoingFile[] = []) => ask(active ? active.wrap(text) : text, files);
  const go: LaunchActions = { ask: (t) => { const w = active ? active.wrap(t) : t; collapse(); ask(w); }, then: (f) => { collapse(); f(); } };
  return (
    <>
      {focused && <div className="frost-scrim" onPointerDown={(e) => { e.preventDefault(); collapse(); }} />}
      <div ref={box} className="launch" onFocus={() => setFocused(true)}
        onBlur={(e) => { if (!box.current?.contains(e.relatedTarget as Node | null)) end(); }}
        onKeyDown={(e) => { if (e.key === "Escape") collapse(); }}>
        {active ? (
          <>
            {active.extras(go)}
            <div className="launch-caption">{active.caption}</div>
          </>
        ) : focused && (
          <div className="launch-chips">
            {suggestions.map((s, i) => (
              <button key={s} className="glass" style={stagger(i)} onMouseDown={(e) => e.preventDefault()} onClick={() => ask(s)}>{s}</button>
            ))}
          </div>
        )}
        <Composer disabled={false} onSend={send}
          placeholder={active ? active.caption : undefined} hints={active?.hints} hintIcons={active?.hintIcons} attach={!active}
          leading={focused ? <button className="glass-btn glass composer-lead" onMouseDown={(e) => e.preventDefault()} onClick={collapse} aria-label="收起"><IconChevronDown /></button> : undefined} />
      </div>
    </>
  );
}
