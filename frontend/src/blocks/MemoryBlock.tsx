import { useState } from "react";
import { Link } from "react-router-dom";
import { memoryCardState, type MemoryCardState } from "../lib/memory";
import { useMemories } from "../lib/memoryStore";
import type { MemoryBlock as T } from "../lib/types";
import { IconBrain, IconChevron } from "../ui/icons";

const TITLE: Record<T["action"], [string, string]> = { // [生效时, 撤销后]
  saved: ["已记住", "已撤销记住"],
  updated: ["已更新记忆", "已改回原来的说法"],
  forgotten: ["已忘掉", "已恢复"],
};

/** 记忆卡（= App blocks/memory_block.dart）：安静的一条便签。状态对照共享记忆列表推算；撤销 = 删 / 改回 / 重建。 */
export default function MemoryBlock({ block }: { block: T }) {
  const mem = useMemories();
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  const state: MemoryCardState = memoryCardState(block, mem.loaded ? mem.items : null);
  const undone = state === "undone";
  const strike = undone !== (block.action === "forgotten"); // 不再生效的那句划掉

  const undo = async () => {
    setBusy(true); setFailed(false);
    try {
      for (const i of block.items) {
        if (block.action === "saved") await mem.remove(i.id);
        else if (block.action === "updated") await mem.update(i.id, { content: i.previous ?? "" });
        else await mem.create({ content: i.content, category: i.category });
      }
    } catch { setFailed(true); } finally { setBusy(false); }
  };

  const title = TITLE[block.action][undone ? 1 : 0];
  return (
    <div className={`blk-memory ${state}`} aria-label={`${title}：${block.items.map((i) => i.content).join("；")}`}>
      <div className="blk-memory-head">
        <IconBrain size={16} />
        <span key={title} className="blk-memory-title fade-in">{failed ? "没撤销成功，稍后再试" : title}</span>
        {state === "active" && (
          <button className="btn btn-ghost btn-sm fade-in" disabled={busy} onClick={undo}>{block.action === "forgotten" ? "恢复" : "撤销"}</button>
        )}
        <Link className="icon-btn sm" to="/me/memory" aria-label="管理记忆" title="管理记忆"><IconChevron /></Link>
      </div>
      {block.items.map((i) => (
        <div key={i.id + i.content}>
          <div className={`blk-memory-line ${strike ? "struck" : ""}`}>{i.content}</div>
          {i.previous && !undone && <div className="blk-memory-prev">原来：{i.previous}</div>}
        </div>
      ))}
    </div>
  );
}
