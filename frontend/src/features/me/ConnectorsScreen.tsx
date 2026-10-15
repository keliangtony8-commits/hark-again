import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useResource } from "../../hooks/useResource";
import { http } from "../../lib/api";
import type { Connector, McpServerInfo, VaultSecret } from "../../lib/types";
import { withRetried } from "../../lib/taskLabels";
import { IconAlert, IconChevron, IconPlus, IconSettings, IconSpark } from "../../ui/icons";
import { Menu, Page, PageHeader, PageIntro, Section, Sheet, Skeleton, StarterCard, stagger } from "../../ui/kit";
import { ADD_KINDS, connectorSummary, groupSecrets, mcpProblemText, missingSetup, setupLine, sortAccounts, sortServers } from "./connectorLibrary";
import SecretSheet, { SecretRows, secretKindIcon, type SecretDraftStart } from "./SecretSheet";
import OAuthSetupSheet from "./OAuthSetupSheet";
import { confirmDialog } from "../../ui/dialog";
import { monogramOf } from "../../lib/monogram";
import { connectorAuthorizable, connectorStatus, startConnect } from "../../lib/connect";

const favicon = (domain: string) => `https://icons.duckduckgo.com/ip3/${domain}.ico`;
const EMPTY_MCP = { name: "", url: "", token: "" };
const hostOf = (url: string) => { try { return new URL(url).host; } catch { return url; } };

/** 品牌小图标；取不到（离线、被拦）就换成名字首字的字标，不露破图。 */
function ConnectorLogo({ c }: { c: Connector }) {
  const [broken, setBroken] = useState(false);
  if (broken || !c.logo) return <span className="row-monogram" aria-hidden="true">{monogramOf(c.name)}</span>;
  return <img src={favicon(c.logo)} alt="" width={20} height={20} onError={() => setBroken(true)} />;
}

/** 连接的账号（v2.96 一页，= App connectors_screen.dart）：账户（OAuth）→ MCP 服务器 → 网站登录 → API Key → 环境变量，
 *  按“越省事越靠前”分区，有内容才出现；页头 + 是唯一的添加入口（ADD_KINDS）；MCP 与密钥都空时一张起步卡。
 *  原来的保险箱页、“账户”收拢页已并进来、删除。 */
export default function ConnectorsScreen() {
  const accounts = useResource<Connector>("/api/connectors");
  const servers = useResource<McpServerInfo>("/api/connectors/mcp");
  const secrets = useResource<VaultSecret>("/api/vault");
  const [secretStart, setSecretStart] = useState<SecretDraftStart | null>(null);
  const [params, setParams] = useSearchParams();
  const [notice, setNotice] = useState<{ ok: boolean; text: string } | null>(null);
  const [mcpDraft, setMcpDraft] = useState<typeof EMPTY_MCP | null>(null);
  const [mcpBusy, setMcpBusy] = useState(false);
  const [mcpErr, setMcpErr] = useState<string | null>(null);
  const [setupOpen, setSetupOpen] = useState(false);
  const [tools, setTools] = useState<{ server: McpServerInfo; list: { name: string; description?: string }[] | null; err?: string } | null>(null);

  // OAuth 回调带回来的结果：提示一次后清掉
  useEffect(() => {
    const ok = params.get("connected"), err = params.get("error");
    if (ok || err) {
      setNotice(ok ? { ok: true, text: withRetried("连接成功", params.get("retried")) } : { ok: false, text: `连接失败：${err}` });
      setParams({}, { replace: true });
    }
  }, [params, setParams]);

  const connect = async (c: Connector) => {
    try { await startConnect(c.id); }
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
    catch (e) { setTools({ server, list: [], err: e instanceof Error ? e.message : "无法连接" }); }
    finally { void servers.reload(); } // 打开工具列表 = 一次体检（后端据此放 / 收主页提醒），刷新这一行的状态
  };
  const addMcp = async () => {
    if (!mcpDraft) return;
    setMcpBusy(true); setMcpErr(null);
    try {
      const added = await http.post<McpServerInfo>("/api/connectors/mcp", mcpDraft);
      await servers.reload(); setMcpDraft(null);
      setNotice({ ok: true, text: withRetried(`已连接 ${added.name}`, added.retried_note) });
    }
    catch (e) { setMcpErr(e instanceof Error ? e.message : "添加失败"); }
    finally { setMcpBusy(false); }
  };

  const add = (kind: string) => (kind === "mcp" ? openMcp() : setSecretStart({ kind: kind as SecretDraftStart["kind"] }));
  const addIcon = (kind: string, size?: number) => (kind === "mcp" ? <IconSpark size={size} /> : secretKindIcon(kind, size));
  const shown = sortAccounts(accounts.items), missing = missingSetup(accounts.items);
  const g = groupSecrets(secrets.items);
  const secretGroups = [{ title: "网站登录", items: g.logins }, { title: "API Key", items: g.keys }, { title: "环境变量", items: g.envs }];
  let n = 0;
  return (
    <Page header={<PageHeader title="连接的账号" back action={
      <Menu trigger={<IconPlus />} label="添加" triggerClass="icon-btn" items={ADD_KINDS.map((k) => (
        { label: `${k.label} · ${k.desc}`, icon: addIcon(k.kind), onSelect: () => add(k.kind) }))} />} />}>
      <PageIntro loading={accounts.loading} summary={connectorSummary(accounts.items, servers.loading ? null : servers.items, secrets.loading ? null : secrets.items)}
        line="一键授权的账号、MCP 服务器，以及加密保存的网站登录、API Key 和环境变量。发邮件、提交代码这类动作，永远先问你；密钥我只知道“有”，看不到内容。" />
      {notice && <div className={`notice ${notice.ok ? "ok" : "err"}`} onClick={() => setNotice(null)}>{notice.text}</div>}

      {/* v2.90.2 只画服务器配好了的（或已连过的）；缺配置时给部署者一行，点开是引导，不放点了会失败的按钮 */}
      {(accounts.loading || shown.length > 0 || missing.length > 0) && (
        <Section title={shown.length ? `账户 · ${shown.length}` : "账户"}>
          {accounts.loading ? <Skeleton rows={2} /> : (
            <div className="list">
              {shown.map((c) => {
                const can = connectorAuthorizable(c), expired = connectorStatus(c) === "expired";
                return (
                  <div key={c.id} className="row enter" style={stagger(++n)}>
                    <span className="row-icon"><ConnectorLogo c={c} /></span>
                    <div className="row-body">
                      <div className="row-title">{c.name}</div>
                      <div className="row-sub">{expired && <><span className="row-problem">授权失效</span> · </>}{c.account ?? c.desc}</div>
                    </div>
                    {c.account ? <>
                      {expired && can
                        ? <button className="btn btn-primary btn-sm" onClick={() => connect(c)}>重新连接</button>
                        : <span className="row-hint">{expired ? "授权失效" : "已连接"}</span>}
                      <button className="btn btn-ghost btn-sm" onClick={() => disconnect(c)}>断开</button>
                    </> : <button className="btn btn-primary btn-sm" onClick={() => connect(c)}>连接</button>}
                  </div>
                );
              })}
              {missing.length > 0 && (
                <button className="row enter" style={stagger(++n)} onClick={() => setSetupOpen(true)}>
                  <span className="row-icon"><IconSettings /></span>
                  <span className="row-body"><span className="row-title">服务器还差一步</span><span className="row-sub">{setupLine(missing)}</span></span>
                  <span className="row-trail"><IconChevron /></span>
                </button>
              )}
            </div>
          )}
        </Section>
      )}

      {servers.items.length > 0 && (
        <Section title={`MCP 服务器 · ${servers.items.length}`}>
          <div className="list">
            {sortServers(servers.items).map((s) => (
              <div key={s.id} className="row enter" style={stagger(++n)}>
                <button className="task-row" onClick={() => void showTools(s)}>
                  <span className="row-icon"><IconSpark /></span>
                  <span className="row-body"><span className="row-title">{s.name}</span>
                    <span className="row-sub">{mcpProblemText(s) && <><span className="row-problem">{mcpProblemText(s)}</span> · </>}{hostOf(s.url)}</span></span>
                  {mcpProblemText(s)
                    ? <span className="row-problem-icon icon-pop" role="img" aria-label={mcpProblemText(s)!}><IconAlert /></span>
                    : s.has_token && <span className="row-hint">带令牌</span>}
                </button>
                <button className="btn btn-ghost btn-sm" onClick={async () => { if (await confirmDialog({ title: `移除 ${s.name}？`, action: "移除" })) void servers.remove(s.id); }}>移除</button>
              </div>
            ))}
          </div>
        </Section>
      )}

      {secretGroups.map(({ title, items }) => {
        if (!items.length) return null;
        const from = n + 1; n += items.length;
        return <Section key={title} title={`${title} · ${items.length}`}><SecretRows items={items} secrets={secrets} onEdit={setSecretStart} from={from} /></Section>;
      })}

      {servers.items.length + secrets.items.length > 0 ? null : (servers.loading || secrets.loading) ? <Skeleton rows={1} /> : (
        <StarterCard title="接入更多服务" text="没有一键授权的服务，也能接进来：填一个 MCP 地址我就能用它的工具；存一个网站登录，我在云浏览器里替你登录；存一个 API Key，我就能调用那个服务；存一个环境变量，你电脑上的程序就能读到它。">
          {ADD_KINDS.map((k) => <button key={k.kind} className="btn btn-ghost" onClick={() => add(k.kind)}>{addIcon(k.kind, 16)}{k.label}</button>)}
        </StarterCard>
      )}

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

      {secretStart && <SecretSheet key={`${secretStart.kind}:${secretStart.name ?? ""}`} start={secretStart} secrets={secrets}
        onClose={() => setSecretStart(null)} onSaved={(text) => setNotice({ ok: true, text })} />}

      {setupOpen && <OAuthSetupSheet missing={missing} onClose={() => setSetupOpen(false)} />}

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
