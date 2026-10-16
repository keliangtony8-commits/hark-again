import { useEffect, useRef } from "react";
import type { ConversationUsage } from "../lib/usage";
import { useSwr } from "./useSwr";

/** 本对话累计用量。和 App 的 conversationUsageProvider 同规则：按对话缓存（useSwr），切回看过的对话立刻有数、后台对齐；
 *  一轮回复结束（streaming true→false）再取一次；刷新期间沿用旧值；没数据时出错 / 离线返回 null（顶栏那行就不显示）。 */
export function useConversationUsage(id: string | null, streaming: boolean) {
  const { data, reload } = useSwr<ConversationUsage>(id ? `/api/conversations/${id}/usage` : null);
  const wasStreaming = useRef(streaming);

  useEffect(() => {
    if (wasStreaming.current && !streaming) void reload();
    wasStreaming.current = streaming;
  }, [streaming, reload]);

  return { usage: data ?? null, reload: () => void reload() };
}
