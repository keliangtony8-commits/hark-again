import { useEffect, useRef, useState } from "react";
import { fileUrl, http } from "../lib/api";
import {
  HANDOFF_CANCEL, HANDOFF_DONE, HANDOFF_TITLE, browserFileLabel, browserFileLine, browserScreenLabel, controlLabel, handoffStateLine, screenInterval, screenShouldPause,
} from "../lib/browserView";
import type { BrowserBlock as T } from "../lib/types";
import { useBlockActions } from "./actions";
import { workspaceFilePath } from "../lib/workspace";
import { IconChevron, IconDownload, IconGlobe, IconHand, IconSend, IconUpload } from "../ui/icons";

/** 云浏览器实时画面：只在卡片可见、页面在前台时刷新截图，节奏见 lib/browserView（操作中快、打开中中、看着慢，
 *  只是看着 2 分钟后暂停，点一下继续）。点“接管”后点画面 = 点网页，下方输入框 = 键盘。
 *  每个请求带卡上的会话名（v1.26 按网站分会话），卡头写网站名；block.live = 还在打开：没画面时显示“正在打开”，不当作没开。
 *  v1.29 接管交还：block.handoff pending = 助手在等你 → 自动接管、出“需要你来”条，完成/做不了走 replyForm(id, {} | null)。
 *  v1.32 画面下列出这条回复传到网页上的 / 网页下载存进工作区的文件（block.files），点开 = 工作区文件。 */
export default function BrowserBlock({ block }: { block: T }) {
  const session = block.session || "main";
  const { replyForm } = useBlockActions();
  const box = useRef<HTMLDivElement>(null);
  const idle = useRef(0);
  const [visible, setVisible] = useState(false);
  const [tick, setTick] = useState(0);
  const [broken, setBroken] = useState(false);
  const [paused, setPaused] = useState(false);
  const [manual, setManual] = useState(false);
  const [replied, setReplied] = useState<string | null>(null);
  const [offline, setOffline] = useState(false);
  const [keys, setKeys] = useState("");

  const h = block.handoff ?? null;
  const waiting = !!h && h.state === "pending" && replied !== h.id;
  const control = manual || waiting;
  const live = !!block.live;

  const wake = () => { idle.current = 0; setPaused(false); };

  useEffect(() => {
    const io = new IntersectionObserver(([e]) => setVisible(e.isIntersecting));
    if (box.current) io.observe(box.current);
    return () => io.disconnect();
  }, []);

  useEffect(() => {
    if (!visible || paused) return;
    const every = screenInterval(control, live);
    const id = setInterval(() => {
      idle.current += every;
      if (screenShouldPause(idle.current, control, live, waiting)) { setPaused(true); return; }
      if (!document.hidden) setTick((t) => t + 1);
    }, every);
    return () => clearInterval(id);
  }, [visible, paused, control, live, waiting]);

  useEffect(() => { if (!live) setBroken(false); wake(); }, [live]); // 打开完成：再试一次拿画面
  useEffect(() => { wake(); if (h && h.state !== "pending") setManual(false); }, [h?.id, h?.state]); // eslint-disable-line react-hooks/exhaustive-deps

  const click = (e: React.MouseEvent<HTMLElement>) => {
    if (paused) { wake(); return; }
    wake();
    if (!control) return;
    const r = e.currentTarget.getBoundingClientRect();
    http.post("/api/browser/mouse", { x: (e.clientX - r.left) / r.width, y: (e.clientY - r.top) / r.height, session });
  };
  const sendKeys = async () => {
    wake();
    await http.post("/api/browser/keyboard", keys ? { text: keys, key: "Enter", session } : { key: "Enter", session });
    setKeys("");
  };
  const answer = (done: boolean) => {
    if (!h || !replyForm) return;
    if (!replyForm(h.id, done ? {} : null, false)) { setOffline(true); return; }
    setOffline(false); setReplied(h.id); setManual(false); wake();
  };

  const src = `${fileUrl("/api/browser/screen")}&session=${encodeURIComponent(session)}&t=${tick}`;
  const line = h && h.state !== "pending" ? handoffStateLine(h) : "";
  return (
    <div ref={box} className={`card blk-browser ${control ? "control" : ""}`}>
      <div className="card-head">
        <span className="blk-browser-title"><IconGlobe size={16} /><span className="blk-browser-site">{block.site ?? "云浏览器"}</span>{visible && !broken && !paused && <i className="live-dot" />}</span>
        <button className={`btn btn-sm ${control ? "btn-primary" : "btn-ghost"}`} disabled={waiting} onClick={() => { setManual(!manual); wake(); }}>
          <IconHand />{controlLabel(control)}</button>
      </div>
      {waiting && h && (
        <div className="blk-handoff" role="status" key={h.id}>
          <IconHand size={18} />
          <div className="blk-handoff-text"><b>{HANDOFF_TITLE}</b><span>{h.reason}</span>
            {offline && <span className="blk-handoff-warn">还没连上，连上后再点一次</span>}</div>
          {replyForm && (
            <div className="blk-handoff-actions">
              <button className="btn btn-sm btn-ghost" onClick={() => answer(false)}>{HANDOFF_CANCEL}</button>
              <button className="btn btn-sm btn-primary" onClick={() => answer(true)}>{HANDOFF_DONE}</button>
            </div>
          )}
        </div>
      )}
      {line && <p className="blk-handoff-line" key={`${h?.id}-${h?.state}`}>{line}</p>}
      <div className="blk-browser-stage" onClick={click} aria-label={browserScreenLabel(control, paused, block.site)} role="img">
        {broken && live ? (
          <div className="blk-browser-empty" role="status">正在打开{block.site ? ` ${block.site}` : "网页"}…
            <img hidden alt="" src={src} onLoad={() => setBroken(false)} /></div>
        ) : broken ? (
          <button className="blk-browser-empty" onClick={() => { setBroken(false); wake(); }}>浏览器没有打开或已休眠，点此重试</button>
        ) : (
          <img className="blk-browser-screen" alt="" src={src} onError={() => setBroken(true)} onLoad={() => setBroken(false)} />
        )}
        {paused && <div className="blk-browser-paused">画面已暂停，点一下继续</div>}
      </div>
      {!!block.files?.length && block.workspace && (
        <ul className="blk-browser-files">
          {block.files.map((f) => (
            <li key={`${f.kind}:${f.path}`}>
              <a href={fileUrl(workspaceFilePath(block.workspace!, f.path))} target="_blank" rel="noreferrer" aria-label={browserFileLabel(f)}>
                {f.kind === "upload" ? <IconUpload size={16} /> : <IconDownload size={16} />}
                <span className="blk-browser-file-text"><b>{f.name}</b><small>{browserFileLine(f)}</small></span>
                <IconChevron />
              </a>
            </li>
          ))}
        </ul>
      )}
      {control && (
        <div className="blk-browser-keys">
          <input value={keys} onChange={(e) => setKeys(e.target.value)} placeholder="先点画面里的输入框，再在这里打字"
            type="text" autoComplete="off" onKeyDown={(e) => e.key === "Enter" && !e.nativeEvent.isComposing && sendKeys()} />
          <button className="send-btn" onClick={sendKeys} aria-label="输入"><IconSend /></button>
        </div>
      )}
    </div>
  );
}
