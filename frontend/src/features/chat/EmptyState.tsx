import BrandMark from "../../ui/BrandMark";

const SUGGESTIONS = [
  { title: "帮我规划这周的学习计划", hint: "按科目和截止日期排" },
  { title: "解释一下 Docker 和虚拟机的区别", hint: "用大白话" },
  { title: "写一封请假邮件给导师", hint: "礼貌简洁" },
  { title: "推荐几本入门机器学习的书", hint: "适合本科生" },
];

export default function EmptyState({ onPick, subtitle }: { onPick: (t: string) => void; subtitle?: string }) {
  const hour = new Date().getHours();
  const greet = hour < 6 ? "夜深了" : hour < 12 ? "早上好" : hour < 18 ? "下午好" : "晚上好";
  return (
    <div className="empty">
      <div className="empty-inner">
        <BrandMark />
        <h1>{greet}</h1>
        <p>{subtitle ?? "今天想先搞定哪件事？"}</p>
        <div className="suggestions">
          {SUGGESTIONS.map((s) => (
            <button key={s.title} className="suggestion" onClick={() => onPick(s.title)}>
              {s.title}<small>{s.hint}</small>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
