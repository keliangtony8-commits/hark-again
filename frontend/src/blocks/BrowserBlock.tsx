import { useCallback, useEffect, useRef, useState } from "react";
import { fileUrl } from "../lib/api";
import {
  BROWSER_DOWN_HINT, BROWSER_DOWN_TITLE, TAKEOVER_LABEL, browserFileLabel, browserFileLine, browserScreenLabel, handoffStateLine, screenInterval, screenShouldPause,
} from "../lib/browserView";
import type { BrowserBlock as T } from "../lib/types";
import { useBlockActions } from "./actions";
import { workspaceFilePath } from "../lib/workspace";
import { IconChevron, IconDownload, IconGlobe, IconGlobeOff, IconHand, IconUpload } from "../ui/icons";
import BrowserTakeover from "./BrowserTakeover";
import { HandoffBar } from "./HandoffBar";

/** 已自动打开过接管页的 handoff id：列表重渲染时不再弹第二次。 */
const autoOpened = new Set<string>();

/** 云浏览器实时画面：只在卡片可见、页面在前台时刷新截图，节奏见 lib/browserView（操作中快、打开中中、看着慢，
 *  只是看着 2 分钟后暂停，点一下继续）。v2.82：卡片只做预览 + 入口，点画面或“接管”打开全屏接管页 BrowserTakeover（开着时卡片不刷）。
 *  每个请求带卡上的会话名（v1.26 按网站分会话），卡头写网站名；block.live = 还在打开：没画面时显示“正在打开”，不当作没开。
 *  v1.29 接管交还：block.handoff pending = 助手在等你 → 出“需要你来”条并自动打开接管页（每个 handoff 一次，只读不弹），完成/做不了走 replyForm(id, {} | null)。
 *  v1.32 画面下列出这条回复传到网页上的 / 网页下载存进工作区的文件（block.files），点开 = 工作区文件。
 *  v2.28 block.down = 浏览器服务本身不能用：不拉画面、不能接管，画面位置换成一句原因 + 怎么办。 */
export default function BrowserBlock({ block }: { block: T }) {
  const session = block.session || "main";
  const { replyForm } = useBlockActions();
  const box = useRef<HTMLDivElement>(null);
  const idle = useRef(0);
  const [visible, setVisible] = useState(false);
  const [tick, setTick] = useState(0);
  const [broken, setBroken] = useState(false);
  const [paused, setPaused] = useState(false);
  const [open, setOpen] = useState(false);
  const [replied, setReplied] = useState<string | null>(null);
  const [offline, setOffline] = useState(false);

  const h = block.handoff ?? null;
  const waiting = !!h && h.state === "pending" && replied !== h.id;
  const control = waiting;
  const live = !!block.live;
  const down = block.down || null;

  const wake = () => { idle.current = 0; setPaused(false); };

  useEffect(() => {
    const io = new IntersectionObserver(([e]) => setVisible(e.isIntersecting));
    if (box.current) io.observe(box.current);
    return () => io.disconnect();
  }, []);

  useEffect(() => {
    if (!visible || paused || down || open) return;
    const every = screenInterval(control, live);
    const id = setInterval(() => {
      idle.current += every;
      if (screenShouldPause(idle.current, control, live, waiting)) { setPaused(true); return; }
      if (!document.hidden) setTick((t) => t + 1);
    }, every);
    return () => clearInterval(id);
  }, [visible, paused, control, live, waiting, down, open]);

  useEffect(() => { if (!live) setBroken(false); wake(); }, [live]); // 打开完成：再试一次拿画面
  useEffect(() => { wake(); }, [h?.id, h?.state]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { // 助手在等你：直接打开接管页（每个 handoff 一次；只读、服务坏了不弹）
    if (waiting && h && replyForm && !down && !autoOpened.has(h.id)) { autoOpened.add(h.id); setOpen(true); }
  }, [waiting, h?.id, down]); // eslint-disable-line react-hooks/exhaustive-deps

  const click = () => { if (paused) { wake(); return; } setOpen(true); };
  const close = useCallback(() => { setOpen(false); wake(); }, []);
  /** 完成 / 做不了（卡上的条和接管页共用）；没连上返回 false。 */
  const answer = (done: boolean) => {
    if (!h || !replyForm) return false;
    if (!replyForm(h.id, done ? {} : null, false)) { setOffline(true); return false; }
    setOffline(false); setReplied(h.id); wake();
    return true;
  };

  const src = `${fileUrl("/api/browser/screen")}&session=${encodeURIComponent(session)}&t=${tick}`;
  const line = h && h.state !== "pending" ? handoffStateLine(h) : "";
  return (
    <div ref={box} className={`card blk-browser ${control ? "control" : ""}`}>
      <div className="card-head">
        <span className="blk-browser-title"><IconGlobe size={16} /><span className="blk-browser-site">{block.site ?? "云浏览器"}</span>{visible && !broken && !paused && !down && <i className="live-dot" />}</span>
        {!down && <button className="btn btn-sm btn-ghost" onClick={() => setOpen(true)}><IconHand />{TAKEOVER_LABEL}</button>}
      </div>
      {waiting && h && <HandoffBar key={h.id} reason={h.reason} offline={offline} onAnswer={replyForm ? (d) => void answer(d) : undefined} />}
      {line && <p className="blk-handoff-line" key={`${h?.id}-${h?.state}`}>{line}</p>}
      {down ? (
        <div className="blk-browser-down" role="status">
          <IconGlobeOff size={18} />
          <div className="blk-handoff-text"><b>{BROWSER_DOWN_TITLE}</b><span>{down}</span><small>{BROWSER_DOWN_HINT}</small></div>
        </div>
      ) : <div className="blk-browser-stage" onClick={click} aria-label={browserScreenLabel(false, paused, block.site)} role="button" tabIndex={0}>
        {broken && live ? (
          <div className="blk-browser-empty" role="status">正在打开{block.site ? ` ${block.site}` : "网页"}…
            <img hidden alt="" src={src} onLoad={() => setBroken(false)} /></div>
        ) : broken ? (
          <button className="blk-browser-empty" onClick={() => { setBroken(false); wake(); }}>浏览器没有打开或已休眠，点此重试</button>
        ) : (
          <img className="blk-browser-screen" alt="" src={src} onError={() => setBroken(true)} onLoad={() => setBroken(false)} />
        )}
        {paused && <div className="blk-browser-paused">画面已暂停，点一下继续</div>}
      </div>}
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
      {open && <BrowserTakeover block={block} onAnswer={replyForm ? answer : undefined} onClose={close} />}
    </div>
  );
}
