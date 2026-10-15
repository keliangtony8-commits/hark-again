import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import type { ImagesBlock as I } from "../lib/types";
import { IconArrowUpRight, IconClose, IconImageOff } from "../ui/icons";

// 图片一摞（v2.99 E4 ImageStack，= App blocks/image_stack.dart）：一个图片块（后端 show_images 一次的结果）= 一摞。
// 单张：4:3 铺满；多张：最上面一张 4:3，后面最多露两层（向右下错开 + 交替轻转 + 一层底色薄纱），右下角“N 张”。
// 第一次出现时后面几张从正下方扇开到位（keyframes stack-fan 在 styles/base.css；只动 transform；减少动态时直接到位）。
// 点开 = 全屏查看器：原生横向 scroll-snap 左右滑（触屏 / 触控板），← → 翻页、Esc 关；顶部页码，底部说明 + 打开原图。
// 替换了 v2.98 之前的“横排小图条 + 点图跳新标签页”（见 docs/devlog.md v2.99）。

type Item = I["items"][number];
const LAYERS = 2; // = App Layout.stackLayers

export default function ImageStack({ block }: { block: I }) {
  const items = block.items.filter((i) => /^https?:\/\//i.test(i.url));
  const [open, setOpen] = useState(false);
  if (!items.length) return null;
  const n = items.length;
  const layers = Math.min(n - 1, LAYERS);
  const cap = items[0].caption?.trim() ?? "";
  const label = n === 1 ? `图片${cap ? "：" + cap : ""}，查看大图` : `${n} 张图片${cap ? "，第一张：" + cap : ""}，点开左右翻看`;
  return (
    <figure className="image-stack" style={{ ["--layers" as string]: layers }}>
      <button className="image-stack-pile" aria-label={label} onClick={() => setOpen(true)}>
        {Array.from({ length: layers }, (_, k) => layers - k).map((d) => (
          <span key={d} className="image-stack-card back" style={{ ["--d" as string]: d, ["--turn" as string]: d % 2 ? 1 : -1 }} aria-hidden>
            <Img url={items[d].url} />
          </span>
        ))}
        <span className="image-stack-card"><Img url={items[0].url} alt={cap} /></span>
        {n > 1 && <span className="image-stack-count" aria-hidden>{n} 张</span>}
      </button>
      {cap && <figcaption>{cap}</figcaption>}
      {open && <ImageViewer items={items} onClose={() => setOpen(false)} />}
    </figure>
  );
}

/** 一摞里的一张：下好了淡入，坏图留安静的占位图标。 */
function Img({ url, alt = "" }: { url: string; alt?: string }) {
  const [state, setState] = useState<"loading" | "ok" | "bad">("loading");
  return state === "bad"
    ? <span className="image-stack-bad"><IconImageOff /></span>
    : <img src={url} alt={alt} loading="lazy" referrerPolicy="no-referrer" className={state === "ok" ? "ok" : ""}
        onLoad={() => setState("ok")} onError={() => setState("bad")} />;
}

/** 全屏查看器：页面底色盖满、淡入；每页一张整图（竖图横图都不裁）。当前页只由滚动位置算（rAF 节流），不另存一份。 */
function ImageViewer({ items, onClose }: { items: Item[]; onClose: () => void }) {
  const track = useRef<HTMLDivElement>(null);
  const box = useRef<HTMLDivElement>(null);
  const [at, setAt] = useState(0);
  const n = items.length;
  const go = (i: number) => {
    const t = track.current;
    if (t) t.scrollTo({ left: Math.max(0, Math.min(n - 1, i)) * t.clientWidth, behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
  };
  useEffect(() => {
    const back = document.activeElement as HTMLElement | null;
    box.current?.focus({ preventScroll: true });
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); onClose(); }
      else if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
        e.preventDefault();
        const t = track.current;
        if (t) go(Math.round(t.scrollLeft / t.clientWidth) + (e.key === "ArrowRight" ? 1 : -1));
      }
    };
    document.addEventListener("keydown", onKey, true);
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey, true);
      document.body.style.overflow = prev;
      if (back?.isConnected) back.focus({ preventScroll: true });
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const frame = useRef(0);
  const onScroll = () => {
    cancelAnimationFrame(frame.current);
    frame.current = requestAnimationFrame(() => {
      const t = track.current;
      if (t) setAt(Math.round(t.scrollLeft / Math.max(1, t.clientWidth)));
    });
  };
  const cur = items[Math.min(at, n - 1)];
  return createPortal(
    <div ref={box} tabIndex={-1} className="image-viewer" role="dialog" aria-modal="true" aria-label="查看图片">
      <div className="image-viewer-head">
        <span className="image-viewer-page" aria-live="polite">{n > 1 ? `${at + 1} / ${n}` : ""}</span>
        <button className="glass-btn glass" onClick={onClose} aria-label="关闭" title="关闭"><IconClose /></button>
      </div>
      <div ref={track} className="image-viewer-track" onScroll={onScroll}>
        {items.map((it, i) => (
          <div key={it.url + i} className="image-viewer-slide" role="group" aria-roledescription="图片" aria-label={`第 ${i + 1} 张，共 ${n} 张${it.caption ? "：" + it.caption : ""}`}>
            <ViewerImg url={it.url} alt={it.caption ?? ""} />
          </div>
        ))}
      </div>
      <div className="image-viewer-foot">
        <span className="image-viewer-cap">{cur.caption ?? ""}</span>
        <a className="pill" href={cur.url} target="_blank" rel="noopener noreferrer"><IconArrowUpRight size={16} />打开原图</a>
      </div>
    </div>,
    document.body,
  );
}

function ViewerImg({ url, alt }: { url: string; alt: string }) {
  const [state, setState] = useState<"loading" | "ok" | "bad">("loading");
  return state === "bad"
    ? <span className="image-viewer-bad"><IconImageOff />这张图片打不开</span>
    : <img src={url} alt={alt} referrerPolicy="no-referrer" className={state === "ok" ? "ok" : ""}
        onLoad={() => setState("ok")} onError={() => setState("bad")} />;
}
