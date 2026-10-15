import { useEffect, useState } from "react";

/** 上一颗 ≡/+ 钮离开时的形状：项目列表（+）和项目页（≡）是“同一颗钮”（v2.93 §Q，= App MenuPlusHero），
 *  新挂上的钮先画成上一颗的样子，下一帧再转到自己的形状，CSS 过渡完成 morph。null = 还没出现过，直接画终态。 */
let lastShape: boolean | null = null;

/** v2.91 §N / v2.93 §Q 项目左上钮（= App MenuPlusIcon）：plus=false 是“≡”，true 是“+”——上下两条线平移到中线、各转 ±90° 合成竖线，
 *  中线不动 → 十字（--dur-morph 280ms，只动 transform；减弱动效时 base.css 把过渡压到 1ms）。
 *  项目列表：+ = 新建项目（各宽度都显示）；项目页（v2.95）：≡ = 项目切换栏、开着时 + = 新建项目（窄屏才有，宽屏切换栏常驻）。 */
export default function MenuPlus({ plus, onClick, label, mobileOnly = false }: { plus: boolean; onClick: () => void; label: string; mobileOnly?: boolean }) {
  const [shape, setShape] = useState(lastShape ?? plus);
  useEffect(() => {
    // 两帧后再换形状：保证“上一颗的样子”先画出来一帧，过渡才会发生
    let b = 0;
    const a = requestAnimationFrame(() => { b = requestAnimationFrame(() => setShape(plus)); });
    lastShape = plus;
    return () => { cancelAnimationFrame(a); cancelAnimationFrame(b); };
  }, [plus]);
  return (
    <button className={`glass-btn glass morph-btn ${mobileOnly ? "mobile-only" : ""}`} onClick={onClick} aria-label={label} title={label} aria-expanded={mobileOnly ? plus : undefined}>
      <span className={`morph-icon ${shape ? "plus" : ""}`} aria-hidden><i /><i /><i /></span>
    </button>
  );
}
