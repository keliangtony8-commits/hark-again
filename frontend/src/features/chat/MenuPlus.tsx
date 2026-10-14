/** v2.91 §N 项目对话左上钮（= App MenuPlusIcon）：plus=false 是“≡”，true 是“+”——上下两条线平移到中线、各转 ±90° 合成竖线，
 *  中线不动 → 十字（--dur-morph 280ms，只动 transform；减弱动效时 base.css 把过渡压到 1ms）。 */
export default function MenuPlus({ plus, onClick }: { plus: boolean; onClick: () => void }) {
  return (
    <button className="icon-btn mobile-only morph-btn" onClick={onClick} aria-label={plus ? "新对话" : "项目对话"} aria-expanded={plus}>
      <span className={`morph-icon ${plus ? "plus" : ""}`} aria-hidden><i /><i /><i /></span>
    </button>
  );
}
