import { useEffect, useState } from "react";
import { http } from "../../lib/api";
import type { Preferences } from "../../lib/preferences";
import { Segmented } from "../../ui/kit";

/** 回复语言（v2.67，= App ReplyLanguageTile）：“偏好设置”里的一行。选了立即生效（乐观），失败退回并在说明行提示。
 *  对话里说“以后用英文回我”时助手改的是同一个设置；每次进“我的”页都重新取。没取到（老服务器）不画这一行。 */
export default function ReplyLanguageRow() {
  const [p, setP] = useState<Preferences | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let live = true;
    http.get<Preferences>("/api/preferences").then((j) => { if (live) setP(j); }).catch(() => {});
    return () => { live = false; };
  }, []);
  // 老服务器 / 形状不对时 reply_languages 可能没有：这时不画这一行，别让整个页面白掉
  if (!p || !p.reply_languages?.length) return null;
  const pick = (code: string) => {
    if (code === p.reply_language) return;
    const old = p;
    setP({ ...p, reply_language: code });
    setFailed(false);
    http.patch<Preferences>("/api/preferences", { reply_language: code }).then(setP).catch(() => { setP(old); setFailed(true); });
  };
  return (
    <div className="row me-appearance me-language">
      <div className="row-body">
        <div className="row-title">回复语言</div>
        <div aria-live="polite">{failed && <div className="row-sub danger-text">没改成，稍后再试</div>}</div>
      </div>
      <Segmented label="回复语言" value={p.reply_language} onChange={pick}
        options={p.reply_languages.map((c) => ({ value: c.code, label: c.label }))} />
    </div>
  );
}
