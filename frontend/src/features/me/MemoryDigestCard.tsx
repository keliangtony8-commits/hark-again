import { useMemoryDigest } from "../../hooks/useMemoryDigest";
import { formatWhen } from "../../lib/format";
import { IconRefresh, IconSpark } from "../../ui/icons";

/** 记忆页顶部的“我对你的了解”。与 App MemoryDigestCard 同逻辑：不自动生成，过期只提示。 */
export default function MemoryDigestCard({ version }: { version: unknown }) {
  const { digest: d, unavailable, generating, error, generate } = useMemoryDigest(version);
  if (unavailable || !d || (d.memories === 0 && !d.text)) return null;
  const has = !!d.text;
  return (
    <section className="digest list" aria-label="我对你的了解">
      <div className="digest-head">
        <span className="row-icon"><IconSpark size={18} /></span>
        <h3>我对你的了解</h3>
        {has && d.stale && !generating && <span className="chip on">记忆有更新</span>}
      </div>
      <p key={has ? d.generated_at ?? "t" : "empty"} className={`digest-text ${has ? "" : "muted"} ${generating ? "busy" : ""}`}>
        {has ? d.text : `把你的 ${d.memories} 条记忆浓缩成一段话。只在你点生成时调用一次便宜模型。`}
      </p>
      <div className="digest-foot">
        <span className={error ? "danger-text" : ""}>{error ?? (has ? `根据 ${d.count} 条记忆 · ${formatWhen(d.generated_at)}` : "")}</span>
        <button className={`btn btn-sm ${!has || d.stale ? "btn-soft" : "btn-ghost"}`} disabled={generating} onClick={generate}>
          <span className={generating ? "spin" : ""}><IconRefresh size={14} /></span>{generating ? "生成中…" : has ? "更新" : "生成"}
        </button>
      </div>
    </section>
  );
}
