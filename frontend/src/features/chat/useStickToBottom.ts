// 消息流“贴底跟随”的唯一规则（v2.79，用户 10-14 16:02：流式回复没滚到真正的底、往上翻又被拽回去）。
// 和 App features/chat/chat_view.dart 的 followSlack / 回到最新 同义：
//   - 离真正的底部（scrollHeight，含给输入胶囊让出的那段 padding）≤ FOLLOW_SLACK 像素 = 在跟随；
//   - 内容变高（流式文字、卡片展开、图片加载、胶囊长高）只由 ResizeObserver 触发一次贴底，不按每个 token scrollTo；
//   - 用户往上翻（滚轮向上 / scrollTop 变小）立刻停止跟随，出现“回到最新”；点它或自己滑回底部恢复跟随；
//   - 自己发消息 / 换对话 = 回到底部（pin）；搜索定位到某条 = 停止跟随（release）。
import { useEffect, useRef, useState } from "react";

export const FOLLOW_SLACK = 80;

/** 离底部的距离（像素）。 */
export const distanceToBottom = (el: HTMLElement) => el.scrollHeight - el.scrollTop - el.clientHeight;

export function useStickToBottom(active: boolean, deps: unknown[] = []) {
  const ref = useRef<HTMLDivElement>(null);
  const following = useRef(true);
  const lastTop = useRef(0);
  const [away, setAway] = useState(false);

  const setFollowing = (on: boolean) => {
    following.current = on;
    setAway(!on);
  };
  const toBottom = (smooth = false) => {
    const el = ref.current;
    if (!el) return;
    const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
    el.scrollTo({ top: el.scrollHeight, behavior: smooth && !reduce ? "smooth" : "instant" });
    lastTop.current = el.scrollTop;
  };

  const onScroll = () => {
    const el = ref.current;
    if (!el) return;
    // 程序平滑滚到底的半路也会触发 scroll，那时 scrollTop 只增不减；只有“往上”才算用户要看前文
    if (distanceToBottom(el) <= FOLLOW_SLACK) { if (!following.current) setFollowing(true); }
    else if (el.scrollTop < lastTop.current - 1 && following.current) setFollowing(false);
    lastTop.current = el.scrollTop;
  };
  // 滚轮向上：在 scroll 事件之前就停止跟随，避免同一帧里 ResizeObserver 又把它拽回底部
  const onWheel = (e: { deltaY: number }) => { if (e.deltaY < 0 && following.current) setFollowing(false); };

  useEffect(() => {
    const el = ref.current;
    const inner = el?.firstElementChild;
    if (!el || !inner || !active) return;
    const stick = () => { if (following.current) toBottom(); };
    stick();
    const ro = new ResizeObserver(stick);
    ro.observe(inner);
    return () => ro.disconnect();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active, ...deps]);

  return {
    ref, onScroll, onWheel, away,
    /** “回到最新”：平滑滚到底并恢复跟随。 */
    jump: () => { setFollowing(true); toBottom(true); },
    /** 自己发消息 / 换对话：立刻到底并跟随。 */
    pin: () => { setFollowing(true); toBottom(); },
    /** 定位到某条消息：别再被贴底拉走。 */
    release: () => setFollowing(false),
  };
}
