import { useCallback, useEffect, useRef, useState } from "react";
import { fileUrl } from "../lib/api";
import { useBrowserLive, useLiveSnapshot } from "../lib/browserLive";
import {
  BROWSER_DOWN_HINT, BROWSER_DOWN_TITLE, TAKEOVER_LABEL, browserFileLabel, browserFileLine, browserScreenLabel, handoffStateLine,
} from "../lib/browserView";
import type { BrowserBlock as T } from "../lib/types";
import { useBlockActions } from "./actions";
import { workspaceFilePath } from "../lib/workspace";
import { IconChevron, IconDownload, IconGlobe, IconGlobeOff, IconHand, IconUpload } from "../ui/icons";
import BrowserTakeover from "./BrowserTakeover";
import { HandoffBar } from "./HandoffBar";
import { LiveScreen } from "./LiveScreen";

/** 已自动打开过接管页的 handoff id：列表重渲染时不再弹第二次。 */
const autoOpened = new Set<string>();

/** 云浏览器实时画面卡 = 预览 + 接管入口（v2.82）。v2.89 §M：画面是一条 WS 推流（lib/browserLive.ts，卡片拥有、接管页复用），
 *  卡片可见才连、网页隐藏就断；断了退避重连（留着最后一帧），浏览器已关闭 → “重新打开”。
 *  每个连接带卡上的会话名（v1.26 按网站分会话），卡头写网站名；block.live = 还在打开：“没开”当作还没好，接着连。
 *  v1.29 接管交还：block.handoff pending = 助手在等你 → 出“需要你来”条并自动打开接管页（每个 handoff 一次，只读不弹），完成/做不了走 replyForm(id, {} | null)。
 *  v1.32 画面下列出这条回复传到网页上的 / 网页下载存进工作区的文件（block.files），点开 = 工作区文件。
 *  v2.28 block.down = 浏览器服务本身不能用：不连画面、不能接管，画面位置换成一句原因 + 怎么办。 */
export default function BrowserBlock({ block }: { block: T }) {
  const session = block.session || "main";
  const { replyForm } = useBlockActions();
  const box = useRef<HTMLDivElement>(null);
  const [visible, setVisible] = useState(false);
  const [open, setOpen] = useState(false);
  const [replied, setReplied] = useState<string | null>(null);
  const [offline, setOffline] = useState(false);

  const h = block.handoff ?? null;
  const waiting = !!h && h.state === "pending" && replied !== h.id;
  const control = waiting;
  const down = block.down || null;
  const live = useBrowserLive(session, !!block.live, (visible || open) && !down);
  const { state } = useLiveSnapshot(live);

  useEffect(() => {
    const io = new IntersectionObserver(([e]) => setVisible(e.isIntersecting));
    if (box.current) io.observe(box.current);
    return () => io.disconnect();
  }, []);
  useEffect(() => { // 卡上画面的物理像素宽：服务器按它缩小帧；接管页开着时由它报
    if (open || !box.current) return;
    live.view(box.current.clientWidth * devicePixelRatio);
  }, [live, open, visible, state]);

  useEffect(() => { // 助手在等你：直接打开接管页（每个 handoff 一次；只读、服务坏了不弹）
    if (waiting && h && replyForm && !down && !autoOpened.has(h.id)) { autoOpened.add(h.id); setOpen(true); }
  }, [waiting, h?.id, down]); // eslint-disable-line react-hooks/exhaustive-deps

  const close = useCallback(() => setOpen(false), []);
  /** 完成 / 做不了（卡上的条和接管页共用）；没连上返回 false。 */
  const answer = (done: boolean) => {
    if (!h || !replyForm) return false;
    if (!replyForm(h.id, done ? {} : null, false)) { setOffline(true); return false; }
    setOffline(false); setReplied(h.id);
    return true;
  };

  const line = h && h.state !== "pending" ? handoffStateLine(h) : "";
  return (
    <div ref={box} className={`card blk-browser ${control ? "control" : ""}`}>
      <div className="card-head">
        <span className="blk-browser-title"><IconGlobe size={16} /><span className="blk-browser-site">{block.site ?? "云浏览器"}</span>{state === "live" && !down && <i className="live-dot" />}</span>
        {!down && <button className="btn btn-sm btn-ghost" onClick={() => setOpen(true)}><IconHand />{TAKEOVER_LABEL}</button>}
      </div>
      {waiting && h && <HandoffBar key={h.id} reason={h.reason} offline={offline} onAnswer={replyForm ? (d) => void answer(d) : undefined} />}
      {line && <p className="blk-handoff-line" key={`${h?.id}-${h?.state}`}>{line}</p>}
      {down ? (
        <div className="blk-browser-down" role="status">
          <IconGlobeOff size={18} />
          <div className="blk-handoff-text"><b>{BROWSER_DOWN_TITLE}</b><span>{down}</span><small>{BROWSER_DOWN_HINT}</small></div>
        </div>
      ) : <div className="blk-browser-stage" onClick={() => setOpen(true)} aria-label={browserScreenLabel(false, block.site)} role="button" tabIndex={0}
          onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && setOpen(true)}>
        <LiveScreen live={live} site={block.site} className="blk-browser-screen" />
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
      {open && <BrowserTakeover block={block} live={live} onAnswer={replyForm ? answer : undefined} onClose={close} />}
    </div>
  );
}
