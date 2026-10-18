import { useState } from "react";
import { useSwr } from "../../hooks/useSwr";
import { http } from "../../lib/api";
import { HOST_ENABLE_TEXT, HOST_INSTALL_HINT, HOST_PATH, HOST_RULES_EMPTY, HOST_RULES_EMPTY_LINE, HOST_SECTION_TITLE, type HostRule,
  type HostStatus, hostCanToggle, hostDetail, hostHint, hostRuleDeleteText, hostRuleDetail, hostToggleTitle } from "../../lib/host";
import { confirmDialog, noticeDialog } from "../../ui/dialog";
import { IconRule, IconServer } from "../../ui/icons";
import { ListGroup, ListRow, Section, Toggle } from "../../ui/kit";
import "./computer.css";
import { useLate } from "./useComputer";

/** “服务器主机”一节（v1.49，= App features/computer/host_section.dart）：主机模式开关 + “以后都允许”的命令规则。
 *  打开前确认一次；没装主机代理 → 开关灰掉 + 一句怎么装；装了连不上 → 行尾“连不上”。规则行：前缀 · 放行过 N 次，删除先确认。
 *  v3.5.1：是“我的电脑”的子页（titled=false 不画节标题）；滚过之后才出来的不放入场动画。
 *  只在“我的电脑”页。加载失败（后端太旧没有这个接口）→ 整节不画。 */
export default function HostSection({ enter, titled = true }: { enter?: number; titled?: boolean }) {
  const late = useLate();
  const { data: s, mutate: setS } = useSwr<HostStatus>(HOST_PATH);
  const [busy, setBusy] = useState(false);
  const [deleting, setDeleting] = useState<Set<string>>(new Set());
  if (!s) return null;

  const toggle = async (on: boolean) => {
    if (on && !await confirmDialog({ title: "打开服务器主机模式？", text: HOST_ENABLE_TEXT, action: "打开" })) return;
    setBusy(true);
    try { setS(await http.put<HostStatus>(HOST_PATH, { enabled: on })); }
    catch (e) { void noticeDialog("切换失败", e instanceof Error ? e.message : undefined); }
    setBusy(false);
  };
  const remove = async (r: HostRule) => {
    if (!await confirmDialog({ title: "删除这条规则？", text: hostRuleDeleteText(r), action: "删除" })) return;
    setDeleting((d) => new Set(d).add(r.id));
    try { setS(await http.del(`${HOST_PATH}/rules/${encodeURIComponent(r.id)}`) as HostStatus); }
    catch (e) { void noticeDialog("删除失败", e instanceof Error ? e.message : undefined); }
    setDeleting((d) => { const n = new Set(d); n.delete(r.id); return n; });
  };
  const hint = hostHint(s);

  return (
    <Section title={titled ? HOST_SECTION_TITLE : undefined} enter={late ? undefined : enter}>
      <ListGroup>
        <ListRow icon={<IconServer />} title={hostToggleTitle(s)} sub={hostDetail(s)} control={<>
          {hint && <span className="row-hint computer-hint is-warn">{hint}</span>}
          <Toggle on={s.enabled} onChange={(v) => void toggle(v)} label="服务器主机模式" disabled={busy || !hostCanToggle(s)} />
        </>} />
      </ListGroup>
      {!s.installed && <p className="computer-host-hint enter">{HOST_INSTALL_HINT}</p>}
      {(s.enabled || s.rules.length > 0) && (
        <ListGroup className="computer-host-rules enter">
          {s.rules.length === 0 ? (
            <ListRow icon={<IconRule />} title={HOST_RULES_EMPTY} sub={HOST_RULES_EMPTY_LINE} />
          ) : s.rules.map((r, i) => (
            <ListRow key={r.id} enter={late ? undefined : i} role="group" label={`以后都允许 ${r.text} 开头的命令，${hostRuleDetail(r)}`}
              icon={<IconRule />} title={<span className="computer-host-rule">{r.text}</span>} sub={hostRuleDetail(r)}
              control={<button className="btn btn-ghost btn-sm" disabled={deleting.has(r.id)} onClick={() => void remove(r)}>
                {deleting.has(r.id) ? "正在删除" : "删除"}</button>} />
          ))}
        </ListGroup>
      )}
    </Section>
  );
}
