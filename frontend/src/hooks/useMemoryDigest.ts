import { useEffect, useRef, useState } from "react";
import { http } from "../lib/api";
import type { MemoryDigest } from "../lib/memory";
import { useSwr } from "./useSwr";

const PATH = "/api/memory-digest";

/** “我对你的了解”。GET 很轻：进页先显示上次的（useSwr）并后台取一次，version（记忆列表的变化）每变一次再静默取；
 *  generate() 才 POST（花 token），从不自动。老服务器没有接口（且没有旧数据）→ unavailable，卡片不显示。 */
export function useMemoryDigest(version: unknown) {
  const { data, error, reload, mutate } = useSwr<MemoryDigest>(PATH);
  const [generating, setGenerating] = useState(false);
  const [genError, setGenError] = useState<string | null>(null);
  const first = useRef(version);

  useEffect(() => { if (version !== first.current) { first.current = version; void reload(); } }, [version, reload]);

  const generate = async () => {
    if (generating) return;
    setGenerating(true); setGenError(null);
    try { mutate(await http.post<MemoryDigest>(PATH, {})); }
    catch { setGenError("生成失败，稍后再试"); }
    finally { setGenerating(false); }
  };

  return { digest: data ?? null, unavailable: !!error, generating, error: genError, generate };
}
