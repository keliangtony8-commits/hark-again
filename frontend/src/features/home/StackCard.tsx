// 主页卡片栈里的一张卡（v2.78 Home 重做，= App features/home/stack_card.dart）：同宽、同圆角、同底色、等距，
// 标题在卡里（主页不再有小节标题）。今天 / 面板 / 收件箱 / 连接引导都用它，节奏只在 home.css .stack-* 定。
// rows = 一列 .row（今天、收件箱），行贴卡边；否则 children 是普通内容（面板的块、引导卡文字）。
import type { CSSProperties, ReactNode } from "react";

export default function StackCard({ title, trailing, rows, children, className = "", style }: {
  title?: string; trailing?: ReactNode; rows?: boolean; children: ReactNode; className?: string; style?: CSSProperties;
}) {
  return (
    <div className={`stack-card enter ${className}`} style={style}>
      {title && <div className="stack-head"><span className="stack-title">{title}</span>{trailing}</div>}
      <div className={rows ? "stack-rows" : "stack-body"}>{children}</div>
    </div>
  );
}
