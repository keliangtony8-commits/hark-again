import { useEffect, useRef, useState } from "react";
import { formatNumber, parseNumber, sameShape } from "../lib/numberParts";

/** 时长 = tokens.css --dur-count（= App Motion.count），曲线 = --ease 的 easeOutCubic。 */
const duration = () => parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--dur-count")) || 700;
const ease = (t: number) => 1 - Math.pow(1 - t, 3);
const reduced = () => matchMedia("(prefers-reduced-motion: reduce)").matches;

/** 数字滚到新值（= App ui/motion.dart CountUp）：第一次出现从 0 滚上来，值变了从眼前的数滚到新值；
 *  不是“恰好一个数字”或换了形状就直接换字；减少动态直接给终值。读屏只念终值（sr-only），滚动中的字 aria-hidden。 */
export default function CountUp({ value }: { value: string }) {
  const [text, setText] = useState(() => {
    const p = parseNumber(value);
    return p && p.value !== 0 && !reduced() ? formatNumber(p, 0) : value;
  });
  const shownNum = useRef(0); // 眼前显示的数（半路又变了从这里接着滚）
  const prev = useRef<string | null>(null);

  useEffect(() => {
    const to = parseNumber(value);
    const from = prev.current === null ? (to ? { ...to, value: 0 } : null) : parseNumber(prev.current);
    prev.current = value;
    if (!to || !from || !sameShape(from, to) || reduced() || to.value === shownNum.current) {
      shownNum.current = to?.value ?? 0;
      setText(value);
      return;
    }
    const start = performance.now(), d = duration(), a = shownNum.current;
    let raf = 0;
    const step = (now: number) => {
      const t = Math.min(1, (now - start) / d);
      shownNum.current = a + (to.value - a) * ease(t);
      setText(t >= 1 ? value : formatNumber(to, shownNum.current));
      if (t < 1) raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [value]);

  return <><span className="sr-only">{value}</span><span aria-hidden>{text}</span></>;
}
