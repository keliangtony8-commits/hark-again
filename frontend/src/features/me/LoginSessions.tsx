import { useCallback, useEffect, useState } from "react";
import { auth, http } from "../../lib/api";
import { LOGIN_SESSIONS_PATH, type LoginSession, loginSessionLine, loginSessionsSummary, signedOutToast } from "../../lib/loginSessions";
import { confirmDialog, noticeDialog } from "../../ui/dialog";
import { IconComputer, IconGlobe, IconLogout, IconPhone } from "../../ui/icons";
import { ListGroup, ListRow, Section } from "../../ui/kit";

/** “安全”页的登录设备一节（v2.61，= App features/me/login_sessions_section.dart；对标 Hark 设置 → 安全）。
 *  本机排第一、行尾“本机”；别的行尾“退出”（确认后立刻作废那台的登录）；别的设备 ≥1 台时组尾“退出其他所有设备”。
 *  服务器连不上 → 整节不画。规则在后端 app/login_sessions.py。 */
export default function LoginSessions({ enter, reloadKey, onNote }: { enter?: number; reloadKey?: unknown; onNote: (text: string) => void }) {
  const [list, setList] = useState<LoginSession[] | null>(null);
  const [busy, setBusy] = useState<Set<string>>(new Set());
  const load = useCallback(() => http.get<{ sessions: LoginSession[] }>(LOGIN_SESSIONS_PATH)
    .then((v) => setList(v.sessions)).catch(() => setList(null)), []);
  useEffect(() => { void load(); }, [load, reloadKey]);
  if (!list) return null;

  const run = async (key: string, job: () => Promise<void>) => {
    setBusy((b) => new Set(b).add(key));
    try { await job(); } catch (e) { void noticeDialog("退出失败", e instanceof Error ? e.message : undefined); }
    setBusy((b) => { const n = new Set(b); n.delete(key); return n; });
  };

  const revoke = async (s: LoginSession) => {
    if (!await confirmDialog({ title: `退出 ${s.label}？`, text: "那台设备会立刻退出，要重新输入密码才能再用。", action: "退出" })) return;
    await run(s.id, async () => {
      await http.del(`${LOGIN_SESSIONS_PATH}/${encodeURIComponent(s.id)}`);
      setList((l) => (l ?? []).filter((x) => x.id !== s.id));
      onNote(`已退出 ${s.label}`);
    });
  };

  const revokeOthers = async () => {
    if (!await confirmDialog({ title: "退出其他所有设备？", text: "除了这台，别的手机、电脑、浏览器都会立刻退出。", action: "全部退出" })) return;
    await run("*", async () => {
      const r = await http.post<{ signed_out: number; token?: string }>(`${LOGIN_SESSIONS_PATH}/revoke-others`, {});
      if (r.token) auth.set(r.token); // 本机是升级前的老登录：服务器换发了新 token
      setList((l) => (l ?? []).filter((x) => x.current));
      onNote(signedOutToast(r.signed_out));
    });
  };

  const others = list.some((s) => !s.current);
  return (
    <Section title="登录设备" action={<span className="section-count">{loginSessionsSummary(list)}</span>} enter={enter}>
      <ListGroup>
        {list.map((s, i) => (
          <ListRow key={s.id} enter={i} icon={s.kind === "app" ? <IconPhone /> : s.kind === "browser" ? <IconComputer /> : <IconGlobe />}
            title={s.label} sub={loginSessionLine(s)} trail={s.current ? "本机" : undefined}
            control={!s.current && <button className="btn btn-ghost btn-sm" disabled={busy.has(s.id)} onClick={() => void revoke(s)}>{busy.has(s.id) ? "正在退出" : "退出"}</button>} />
        ))}
        {others && (
          <ListRow onClick={() => void revokeOthers()} disabled={busy.has("*")} trail={null} icon={<IconLogout />}
            title={<span className="danger-text">{busy.has("*") ? "正在退出…" : "退出其他所有设备"}</span>} sub="手机丢了、在别人电脑上登过时用" />
        )}
      </ListGroup>
    </Section>
  );
}
