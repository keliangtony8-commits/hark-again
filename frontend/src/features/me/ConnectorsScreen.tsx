import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useResource } from "../../hooks/useResource";
import { http } from "../../lib/api";
import type { Connector, McpServerInfo } from "../../lib/types";
import { IconChevron, IconPlus, IconShield, IconSpark } from "../../ui/icons";
import { Page, PageHeader, Section, Sheet, Skeleton } from "../../ui/kit";
import { confirmDialog } from "../../ui/dialog";

const favicon = (domain: string) => `https://icons.duckduckgo.com/ip3/${domain}.ico`;
const EMPTY_MCP = { name: "", url: "", token: "" };

/** 连接的账户：OAuth 账户、MCP 服务器、API Key 三种接入方式，按“越省事越靠前”排列。 */
export default function ConnectorsScreen() {
  const accounts = useResource<Connector>("/api/connectors");
  const servers = useResource<McpServerInfo>("/api/connectors/mcp");
  const [params, setParams] = useSearchParams();
  const [notice, setNotice] = useState<{ ok: boolean; text: string } | null>(null);
  const [mcpDraft, setMcpDraft] = useState<typeof EMPTY_MCP | null>(null);
  const [mcpBusy, setMcpBusy] = useState(false);
  const [mcpErr, setMcpErr] = useState<string | null>(null);

  // OAuth 回调带回来的结果：提示一次后清掉
  useEffect(() => {
    const ok = params.get("connected"), err = params.get("error");
    if (ok || err) {
      setNotice(ok ? { ok: true, text: "连接成功" } : { ok: false, text: `连接失败：${err}` });
      setParams({}, { replace: true });
    }
  }, [params, setParams]);

  const connect = async (c: Connector) => {
    try { window.location.href = (await http.get<{ url: string }>(`/api/connectors/${c.id}/start`)).url; }
    catch (e) { setNotice({ ok: false, text: e instanceof Error ? e.message : "无法开始连接" }); }
  };
  const disconnect = async (c: Connector) => {
    if (!(await confirmDialog({ title: `断开 ${c.name}？`, text: `账号 ${c.account} 的授权会被撤销，用到它的任务会停下。`, action: "断开" }))) return;
    await http.del(`/api/connectors/${c.id}`);
    accounts.reload();
  };
  const addMcp = async () => {
    if (!mcpDraft) return;
    setMcpBusy(true); setMcpErr(null);
    try { await http.post("/api/connectors/mcp", mcpDraft); await servers.reload(); setMcpDraft(null); }
    catch (e) { setMcpErr(e instanceof Error ? e.message : "添加失败"); }
    finally { setMcpBusy(false); }
  };

  return (
    <Page header={<PageHeader title="连接的账户" back />}>
      <p className="desc">连接后我能读你的邮件、日历和代码仓库。发邮件、提交代码这类动作，永远先问你。</p>
      {notice && <div className={`notice ${notice.ok ? "ok" : "err"}`} onClick={() => setNotice(null)}>{notice.text}</div>}

      <Section title="账户">
        {accounts.loading ? <Skeleton rows={2} /> : (
          <div className="list">
            {accounts.items.map((c) => (
              <div key={c.id} className="row">
                <span className="row-icon"><img src={favicon(c.logo)} alt="" width={20} height={20} /></span>
                <div className="row-body">
                  <div className="row-title">{c.name}</div>
                  <div className="row-sub">{c.account ?? (c.configured ? c.desc : "服务器还没配置这个应用")}</div>
                </div>
                {c.account ? <button className="btn btn-ghost btn-sm" onClick={() => disconnect(c)}>断开</button>
                  : <button className="btn btn-primary btn-sm" disabled={!c.configured} onClick={() => connect(c)}>连接</button>}
              </div>
            ))}
          </div>
        )}
      </Section>

      <Section title="MCP 服务器" action={<button className="icon-btn" onClick={() => { setMcpDraft(EMPTY_MCP); setMcpErr(null); }} aria-label="添加 MCP"><IconPlus /></button>}>
        <div className="list">
          {servers.items.length === 0 ? (
            <div className="row"><div className="row-body"><div className="row-sub">接入任意 MCP 工具：填地址，我会先连一次确认能用。</div></div></div>
          ) : servers.items.map((s) => (
            <div key={s.id} className="row">
              <span className="row-icon"><IconSpark /></span>
              <div className="row-body"><div className="row-title">{s.name}</div><div className="row-sub">{s.url}</div></div>
              <button className="btn btn-danger btn-sm" onClick={async () => { if (await confirmDialog({ title: `移除 ${s.name}？`, action: "移除" })) void servers.remove(s.id); }}>移除</button>
            </div>
          ))}
        </div>
      </Section>

      <Section title="其他服务">
        <div className="list">
          <Link to="/me/vault" className="row">
            <span className="row-icon"><IconShield /></span>
            <div className="row-body"><div className="row-title">API Key</div><div className="row-sub">任何有 API 的服务：密钥存进保险箱，按域名使用</div></div>
            <span className="row-trail"><IconChevron /></span>
          </Link>
        </div>
      </Section>

      {mcpDraft && (
        <Sheet title="添加 MCP 服务器" onClose={() => setMcpDraft(null)} actions={<>
          <button className="btn btn-ghost" onClick={() => setMcpDraft(null)}>取消</button>
          <button className="btn btn-primary" disabled={mcpBusy || !mcpDraft.name.trim() || !mcpDraft.url.trim()} onClick={addMcp}>{mcpBusy ? "连接中…" : "连接并保存"}</button>
        </>}>
          <label className="form-field"><span>名称</span>
            <input value={mcpDraft.name} onChange={(e) => setMcpDraft({ ...mcpDraft, name: e.target.value })} placeholder="天气" /></label>
          <label className="form-field"><span>地址（Streamable HTTP）</span>
            <input value={mcpDraft.url} onChange={(e) => setMcpDraft({ ...mcpDraft, url: e.target.value })} placeholder="https://example.com/mcp" autoCapitalize="off" /></label>
          <label className="form-field"><span>令牌（可选）</span>
            <input type="password" autoComplete="off" value={mcpDraft.token} onChange={(e) => setMcpDraft({ ...mcpDraft, token: e.target.value })} placeholder="加密保存，不会再显示" /></label>
          {mcpErr && <div className="error-banner">{mcpErr}</div>}
        </Sheet>
      )}
    </Page>
  );
}
