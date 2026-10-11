import { useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import Composer from "../features/chat/Composer";
import type { Upload } from "../lib/types";
import { IconChevronDown } from "../ui/icons";

export const STARTER_PROMPTS = ["帮我规划这周的学习", "查一下今天的新闻", "把这段话翻译成英文", "每天早上 8 点给我简报"];

/** 跳到聊天并在新对话里发出（ChatScreen 读路由状态 draft/files）。主页、项目页、新面板都走它。 */
export function useAskInNewChat() {
  const nav = useNavigate();
  return (text: string, files: Upload[] = []) => nav("/chat", { state: { draft: text, files } });
}

/** 一级页面（主页、项目列表）底部的输入胶囊：和聊天页同一个 Composer、同一位置、同一外观，发出 = 新对话。
 *  聚焦时整页磨砂变暗、胶囊左边出现“收起”、上方升起建议问题；点遮罩 / 收起 / Esc 收起。和 App shell/launch_composer.dart 同义。 */
export default function LaunchComposer({ suggestions = STARTER_PROMPTS }: { suggestions?: string[] }) {
  const ask = useAskInNewChat();
  const [focused, setFocused] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const collapse = () => { (document.activeElement as HTMLElement | null)?.blur(); setFocused(false); };
  return (
    <>
      {focused && <div className="frost-scrim" onPointerDown={(e) => { e.preventDefault(); collapse(); }} />}
      <div ref={box} className="launch" onFocus={() => setFocused(true)}
        onBlur={(e) => { if (!box.current?.contains(e.relatedTarget as Node | null)) setFocused(false); }}
        onKeyDown={(e) => { if (e.key === "Escape") collapse(); }}>
        {focused && (
          <div className="launch-chips">
            {suggestions.map((s) => (
              <button key={s} className="glass" onMouseDown={(e) => e.preventDefault()} onClick={() => ask(s)}>{s}</button>
            ))}
          </div>
        )}
        <Composer disabled={false} onSend={(t, files) => ask(t, files)}
          leading={focused ? <button className="glass-btn glass composer-lead" onMouseDown={(e) => e.preventDefault()} onClick={collapse} aria-label="收起"><IconChevronDown /></button> : undefined} />
      </div>
    </>
  );
}
