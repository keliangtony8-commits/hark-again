import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useResource } from "../../hooks/useResource";
import { http } from "../../lib/api";
import type { Connector, McpServerInfo } from "../../lib/types";
import { IconChevron, IconPlus, IconShield, IconSpark } from "../../ui/icons";
import { Page, PageHeader, PageIntro, Section, Sheet, Skeleton, StarterCard, stagger } from "../../ui/kit";
import { connectorSummary, sortAccounts } from "./connectorLibrary";
import { confirmDialog } from "../../ui/dialog";

const favicon = (domain: string) => `https://icons.duckduckgo.com/ip3/${domain}.ico`;
const EMPTY_MCP = { name: "", url: "", token: "" };
const hostOf = (url: string) => { try { return new URL(url).host; } catch { return url; } };

/** 连接器：OAuth 账户、MCP 服务器、API Key 三种接入方式，按“越省事越靠前”排列。
 *  版式同技能/定时任务页：页头摘要 → 分区 → 行错峰进场；MCP 为空时起步卡。 */
export default function ConnectorsScreen() {
  const accounts = useResource<Connector>("/api/connectors");
  const servers = useResource<McpServerInfo>("/api/connectors/mcp");
  const [params, setParams] = useSearchParams();
  const [notice, setNotice] = useState<{ ok: boolean; text: string } | null>(null);
  const [mcpDraft, setMcpDraft] = useState<typeof EMPTY_MCP | null>(null);
  const [mcpBusy, setMcpBusy] = useState(false);
  const [mcpErr, setMcpErr] = useState<string | null>(null);
  const [tools, setTools] = useState<{ server: McpServerInfo; list: { name: string; description?: string }[] | null; err?: string } | null>(null);

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
  const openMcp = () => { setMcpDraft(EMPTY_MCP); setMcpErr(null); };
  const showTools = async (server: McpServerInfo) => {
    setTools({ server, list: null });
    try { setTools({ server, list: await http.get(`/api/connectors/mcp/${server.id}/tools`) }); }
    catch (e) { setTools({ server, list: [], err: e instanceof Error ? e.message : "连不上" }); }
  };
  const addMcp = async () => {
    if (!mcpDraft) return;
    setMcpBusy(true); setMcpErr(null);
    try { await http.post("/api/connectors/mcp", mcpDraft); await servers.reload(); setMcpDraft(null); }
    catch (e) { setMcpErr(e instanceof Error ? e.message : "添加失败"); }
    finally { setMcpBusy(false); }
  };

  let n = 0;
  return (
    <Page header={<PageHeader title="连接器" back />}>
      <PageIntro loading={accounts.loading} summary={connectorSummary(accounts.items, servers.loading ? null : servers.items)}
        line="连接后我能读你的邮件、日历和代码仓库。发邮件、提交代码这类动作，永远先问你。" />
      {notice && <div className={`notice ${notice.ok ? "ok" : "err"}`} onClick={() => setNotice(null)}>{notice.text}</div>}

      <Section title={accounts.items.length ? `账户 · ${accounts.items.length}` : "账户"}>
        {accounts.loading ? <Skeleton rows={2} /> : (
          <div className="list">
            {sortAccounts(accounts.items).map((c) => (
              <div key={c.id} className={`row enter ${!c.account && !c.configured ? "row-off" : ""}`} style={stagger(++n)}>
                <span className="row-icon"><img src={favicon(c.logo)} alt="" width={20} height={20} /></span>
                <div className="row-body">
                  <div className="row-title">{c.name}</div>
                  <div className="row-sub">{c.account ?? (c.configured ? c.desc : "服务器还没配置这个应用（见 .env.example）")}</div>
                </div>
                {c.account ? <>
                  <span className="row-hint">已连接</span>
                  <button className="btn btn-ghost btn-sm" onClick={() => disconnect(c)}>断开</button>
                </> : c.configured && <button className="btn btn-primary btn-sm" onClick={() => connect(c)}>连接</button>}
              </div>
            ))}
          </div>
        )}
      </Section>

      <Section title={servers.items.length ? `MCP 服务器 · ${servers.items.length}` : "MCP 服务器"}
        action={servers.items.length > 0 && <button className="icon-btn sm" onClick={openMcp} aria-label="添加 MCP 服务器"><IconPlus /></button>}>
        {servers.loading ? <Skeleton rows={1} /> : servers.items.length === 0 ? (
          <StarterCard title="接入任何 MCP 服务" text="填一个支持 MCP（Streamable HTTP）的地址，我先连一次确认能用，之后就能用它的工具。">
            <button className="btn btn-ghost" onClick={openMcp}><IconPlus size={16} />添加 MCP 服务器</button>
          </StarterCard>
        ) : (
          <div className="list">
            {servers.items.map((s) => (
              <div key={s.id} className="row enter" style={stagger(++n)}>
                <button className="task-row" onClick={() => void showTools(s)}>
                  <span className="row-icon"><IconSpark /></span>
                  <span className="row-body"><span className="row-title">{s.name}</span><span className="row-sub">{hostOf(s.url)}</span></span>
                  {s.has_token && <span className="row-hint">带令牌</span>}
                </button>
                <button className="btn btn-ghost btn-sm" onClick={async () => { if (await confirmDialog({ title: `移除 ${s.name}？`, action: "移除" })) void servers.remove(s.id); }}>移除</button>
              </div>
            ))}
          </div>
        )}
      </Section>

      <Section title="其他服务">
        <div className="list">
          <Link to="/me/vault" className="row enter" style={stagger(++n)}>
            <span className="row-icon"><IconShield /></span>
            <div className="row-body"><div className="row-title">API Key 与网站登录</div><div className="row-sub">没有现成连接器的服务，把钥匙存进保险箱就能用</div></div>
            <span className="row-trail"><IconChevron /></span>
          </Link>
        </div>
      </Section>

      {tools && (
        <Sheet title={tools.server.name} onClose={() => setTools(null)}>
          <span className="page-hero-label">{tools.list ? `${tools.list.length} 个工具 · ${hostOf(tools.server.url)}` : hostOf(tools.server.url)}</span>
          {tools.err ? <div className="error-banner">{tools.err}</div> : !tools.list ? <Skeleton rows={3} /> : tools.list.length === 0 ? (
            <p className="desc">这个服务器连得上，但没有提供任何工具。</p>
          ) : (
            <div className="list">
              {tools.list.map((t, i) => (
                <div key={t.name} className="row enter" style={stagger(i)}>
                  <div className="row-body"><div className="row-title">{t.name}</div><div className="row-sub">{t.description ?? ""}</div></div>
                </div>
              ))}
            </div>
          )}
        </Sheet>
      )}

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
