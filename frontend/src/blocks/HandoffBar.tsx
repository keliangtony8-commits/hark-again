import { HANDOFF_CANCEL, HANDOFF_DONE, HANDOFF_TITLE } from "../lib/browserView";
import { IconHand } from "../ui/icons";

/** “需要你来”条：卡片（BrowserBlock）和接管页（BrowserTakeover）共用这一个（= App HandoffBar）。
 *  onAnswer 为空 = 只读场景，只显示说明；offline = 上次没发出去。 */
export function HandoffBar({ reason, offline, onAnswer }: { reason: string; offline?: boolean; onAnswer?: (done: boolean) => void }) {
  return (
    <div className="blk-handoff" role="status">
      <IconHand size={18} />
      <div className="blk-handoff-text"><b>{HANDOFF_TITLE}</b><span>{reason}</span>
        {offline && <span className="blk-handoff-warn">尚未连接，连接后请重试</span>}</div>
      {onAnswer && (
        <div className="blk-handoff-actions">
          <button className="btn btn-sm btn-ghost" onClick={() => onAnswer(false)}>{HANDOFF_CANCEL}</button>
          <button className="btn btn-sm btn-primary" onClick={() => onAnswer(true)}>{HANDOFF_DONE}</button>
        </div>
      )}
    </div>
  );
}
