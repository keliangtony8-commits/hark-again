import { useCallback, useEffect, useState } from "react";
import { http } from "../../lib/api";
import { HOST_ENABLE_TEXT, HOST_INSTALL_HINT, HOST_PATH, HOST_RULES_EMPTY, HOST_RULES_EMPTY_LINE, HOST_SECTION_TITLE, type HostRule,
  type HostStatus, hostCanToggle, hostDetail, hostHint, hostRuleDeleteText, hostRuleDetail, hostToggleTitle } from "../../lib/host";
import { confirmDialog, noticeDialog } from "../../ui/dialog";
import { IconRule, IconServer } from "../../ui/icons";
import { Section, Toggle } from "../../ui/kit";
import "./computer.css";

/** “服务器主机”一节（v1.49，= App features/computer/host_section.dart）：主机模式开关 + “以后都允许”的命令规则。
 *  打开前确认一次；没装主机代理 → 开关灰掉 + 一句怎么装；装了连不上 → 行尾“连不上”。规则行：前缀 · 放行过 N 次，删除先确认。
 *  只在“我的电脑”页。加载失败（后端太旧没有这个接口）→ 整节不画。 */
export default function HostSection({ enter }: { enter?: number }) {
  const [s, setS] = useState<HostStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [deleting, setDeleting] = useState<Set<string>>(new Set());
  const load = useCallback(() => http.get<HostStatus>(HOST_PATH).then(setS).catch(() => setS(null)), []);
  useEffect(() => { void load(); }, [load]);
  if (!s) return null;

  const toggle = async (on: boolean) => {
    if (on && !await confirmDialog({ title: "打开服务器主机模式？", text: HOST_ENABLE_TEXT, action: "打开" })) return;
    setBusy(true);
    try { setS(await http.put<HostStatus>(HOST_PATH, { enabled: on })); }
    catch (e) { void noticeDialog("没能切换", e instanceof Error ? e.message : undefined); }
    setBusy(false);
  };
  const remove = async (r: HostRule) => {
    if (!await confirmDialog({ title: "删除这条规则？", text: hostRuleDeleteText(r), action: "删除" })) return;
    setDeleting((d) => new Set(d).add(r.id));
    try { setS(await http.del(`${HOST_PATH}/rules/${encodeURIComponent(r.id)}`) as HostStatus); }
    catch (e) { void noticeDialog("没能删除", e instanceof Error ? e.message : undefined); }
    setDeleting((d) => { const n = new Set(d); n.delete(r.id); return n; });
  };
  const hint = hostHint(s);

  return (
    <Section title={HOST_SECTION_TITLE} enter={enter}>
      <div className="list">
        <div className="row">
          <span className="row-icon"><IconServer /></span>
          <div className="row-body"><div className="row-title">{hostToggleTitle(s)}</div><div className="row-sub">{hostDetail(s)}</div></div>
          {hint && <span className="row-hint computer-hint is-warn">{hint}</span>}
          <Toggle on={s.enabled} onChange={(v) => void toggle(v)} label="服务器主机模式" disabled={busy || !hostCanToggle(s)} />
        </div>
      </div>
      {!s.installed && <p className="computer-host-hint enter">{HOST_INSTALL_HINT}</p>}
      {(s.enabled || s.rules.length > 0) && (
        <div className="list computer-host-rules enter">
          {s.rules.length === 0 ? (
            <div className="row"><span className="row-icon"><IconRule /></span>
              <div className="row-body"><div className="row-title">{HOST_RULES_EMPTY}</div><div className="row-sub">{HOST_RULES_EMPTY_LINE}</div></div></div>
          ) : s.rules.map((r, i) => (
            <div key={r.id} className="row enter" style={{ animationDelay: `calc(var(--stagger) * ${i})` }} role="group"
              aria-label={`以后都允许 ${r.text} 开头的命令，${hostRuleDetail(r)}`}>
              <span className="row-icon"><IconRule /></span>
              <div className="row-body" aria-hidden><div className="row-title computer-host-rule">{r.text}</div>
                <div className="row-sub">{hostRuleDetail(r)}</div></div>
              <button className="btn btn-ghost btn-sm" disabled={deleting.has(r.id)} onClick={() => void remove(r)}>
                {deleting.has(r.id) ? "正在删除" : "删除"}</button>
            </div>
          ))}
        </div>
      )}
    </Section>
  );
}
