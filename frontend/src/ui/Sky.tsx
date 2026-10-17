import { useLayoutEffect, useRef, type RefObject } from "react";
import { coverSky, syncSky } from "../lib/sky";

/** v3.3「流光」壁纸（= App ui/sky.dart SkyLayer）：竖向底色 + 三团柔光慢速漂移；颜色来自 lib/sky.ts 写的 --sky-*，画法 styles/base.css .sky。
 *  整个应用只有一层（main.tsx 挂在 #root 外）；顶部渐隐条里的是它的副本（SkyFade）。 */
export function Sky() {
  const ref = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => { if (ref.current) syncSky(ref.current); }, []);
  return (
    <div ref={ref} className="sky" aria-hidden>
      <span className="sky-blob sky-a"><i /></span>
      <span className="sky-blob sky-b"><i /></span>
      <span className="sky-blob sky-c"><i /></span>
    </div>
  );
}

/** 滚动区上沿的渐隐条（= App ShellPage 的 SkyLayer(fade:)，v3.3 B3 代替整区 mask-image）：
 *  一条只有渐隐带那么高的壁纸副本，按自己在视口里的位置反向偏移，和全屏壁纸逐像素重合；自身的遮罩从“全是壁纸”渐变到“全透明”。
 *  壁纸以 α 盖在内容上 = 内容以 1-α 透到壁纸，看上去和原来遮罩滚动区一样，但离屏合成的只有这一窄条。
 *  kind：page = 一级页面（.page，渐隐带见 shell.css），thread = 聊天消息流（.thread，见 chat.css），footer = 底部浮条下（v3.5，height = 底条实高，见 shell.css），sheet = 手机全屏弹层的标题行下（v3.5.1，见 ui.css）。放在滚动区后面、同一个定位父元素里。 */
export function SkyFade({ kind, height }: { kind: "page" | "thread" | "footer" | "sheet"; height?: number }) {
  const ref = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const place = () => {
      const r = el.getBoundingClientRect();
      el.style.setProperty("--sky-x", `${r.left}px`);
      el.style.setProperty("--sky-y", `${r.top}px`);
    };
    place();
    const ro = new ResizeObserver(place);
    ro.observe(el); // footer：条随底条长高，上沿在视口里的位置跟着变
    if (el.parentElement) ro.observe(el.parentElement);
    window.addEventListener("resize", place);
    return () => { ro.disconnect(); window.removeEventListener("resize", place); };
  }, []);
  return <div ref={ref} className={`sky-fade sky-fade-${kind}`} style={height === undefined ? undefined : { height }} aria-hidden><Sky /></div>;
}

/** 整屏不透明浮层（.takeover / .image-viewer）挂载后用：自身进场动画（淡入 / 弹出时壁纸还透得出来）全部结束后才算盖住，
 *  卸载时在同一次提交里撤销（这两个浮层没有退场动画），所以壁纸重新出现的那一帧之前柔光就已恢复。减少动态下没有进场动画 → 立刻盖住。 */
export function useSkyCover(ref: RefObject<HTMLElement>) {
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    let release: (() => void) | null = null;
    let alive = true;
    const cover = () => { if (alive && !release) release = coverSky(); };
    Promise.all(el.getAnimations().map((a) => a.finished)).then(cover, cover);
    return () => { alive = false; release?.(); };
  }, [ref]);
}
