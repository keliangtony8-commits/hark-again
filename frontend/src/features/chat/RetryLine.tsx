// 生成中回复上方的一行（v1.50，与 App features/chat/retry_line.dart 同一套）：模型调用失败、正在自动重试
// （“模型那边限流了，正在重试 2/5”），或重试用完换了备用模型（“刚才模型服务器出错了，这一轮改用「快速」”）。
// 和“用了 N 步”那行同一排版；图标 warning 色；次数变了文字重新升起（key 随文字变）。读屏 polite 播报。规则在 lib/retry.ts。
import { retryLabel, retryText, type RetryNotice } from "../../lib/retry";
import { IconRefresh, IconSwap } from "../../ui/icons";

export default function RetryLine({ notice }: { notice: RetryNotice }) {
  const text = retryText(notice);
  return (
    <div className="retry-line" role="status" aria-live="polite" aria-label={retryLabel(notice)}>
      <span className="retry-icon" key={notice.fallback ? "swap" : "retry"} aria-hidden>
        {notice.fallback ? <IconSwap size={14} /> : <IconRefresh size={14} />}
      </span>
      <span className="retry-text" key={text}>{text}</span>
    </div>
  );
}
