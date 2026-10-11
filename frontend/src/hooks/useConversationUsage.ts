import { useEffect, useRef, useState } from "react";
import { http } from "../lib/api";
import type { ConversationUsage } from "../lib/usage";

/** 本对话累计用量。和 App 的 conversationUsageProvider 同规则：
 *  换对话时取一次，一轮回复结束（streaming true→false）再取一次；刷新期间沿用旧值；出错/离线返回 null（顶栏那行就不显示）。 */
export function useConversationUsage(id: string | null, streaming: boolean) {
  const [state, setState] = useState<{ id: string | null; data: ConversationUsage | null }>({ id: null, data: null });
  const [tick, setTick] = useState(0);
  const wasStreaming = useRef(streaming);

  useEffect(() => {
    if (wasStreaming.current && !streaming) setTick((t) => t + 1);
    wasStreaming.current = streaming;
  }, [streaming]);

  useEffect(() => {
    if (!id) return;
    let live = true;
    http.get<ConversationUsage>(`/api/conversations/${id}/usage`)
      .then((data) => { if (live) setState({ id, data }); })
      .catch(() => { if (live) setState((s) => (s.id === id ? s : { id, data: null })); });
    return () => { live = false; };
  }, [id, tick]);

  const reload = () => setTick((t) => t + 1);
  return { usage: id && state.id === id ? state.data : null, reload };
}
