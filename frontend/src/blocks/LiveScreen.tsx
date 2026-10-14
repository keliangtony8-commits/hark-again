import { type BrowserLive, useLiveSnapshot } from "../lib/browserLive";
import { LIVE_REOPEN, liveCanReopen, liveStatusLine } from "../lib/browserView";

/** 实时画面（卡片和接管页共用，= App blocks/browser_block.dart LiveScreen）：最新一帧 + 状态
 *  （重连中先留着最后一帧，盖一层淡淡的说明；关了 / 服务坏了给“重新打开”）。 */
export function LiveScreen({ live, site, className }: { live: BrowserLive; site?: string; className: string }) {
  const { state, frame } = useLiveSnapshot(live);
  const line = liveStatusLine(state, !!frame, live.opening, site);
  return (
    <div className={`live-screen ${className}`}>
      {frame ? <img alt="" src={frame} draggable={false} /> : <div className="live-screen-blank" />}
      {line && (
        <div className={`live-screen-veil ${frame ? "dim" : ""}`} role="status" key={state}>
          <span>{line}</span>
          {liveCanReopen(state) && (
            <button className="btn btn-sm" onClick={(e) => { e.stopPropagation(); live.reopen(); }}>{LIVE_REOPEN}</button>
          )}
        </div>
      )}
    </div>
  );
}
