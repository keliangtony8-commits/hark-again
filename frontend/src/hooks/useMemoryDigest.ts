import { useCallback, useEffect, useRef, useState } from "react";
import { http } from "../lib/api";
import type { MemoryDigest } from "../lib/memory";

const PATH = "/api/memory-digest";

/** “我对你的了解”。GET 很轻：进页取一次，version（记忆列表的变化）每变一次再静默取；
 *  generate() 才 POST（花 token），从不自动。老服务器没有接口 → unavailable，卡片不显示。 */
export function useMemoryDigest(version: unknown) {
  const [digest, setDigest] = useState<MemoryDigest | null>(null);
  const [unavailable, setUnavailable] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const loaded = useRef(false);

  const fetchDigest = useCallback(async () => {
    try { setDigest(await http.get<MemoryDigest>(PATH)); setUnavailable(false); loaded.current = true; }
    catch { if (!loaded.current) setUnavailable(true); }  // 取过一次之后的失败：继续显示旧的
  }, []);

  useEffect(() => { fetchDigest(); }, [fetchDigest, version]);

  const generate = async () => {
    if (generating) return;
    setGenerating(true); setError(null);
    try { setDigest(await http.post<MemoryDigest>(PATH, {})); loaded.current = true; }
    catch { setError("生成失败，稍后再试"); }
    finally { setGenerating(false); }
  };

  return { digest, unavailable, generating, error, generate };
}
