import { useState } from "react";
import { useResource } from "../../hooks/useResource";
import type { VaultSecret } from "../../lib/types";
import { IconEdit, IconMore, IconPlus, IconShield, IconTerminal, IconTrash, IconUser } from "../../ui/icons";
import { Menu, Page, PageHeader, PageIntro, Section, Sheet, Skeleton, StarterCard, stagger } from "../../ui/kit";
import { ENV_VALUE_MIN, SECRET_KINDS, envName, envNameError, groupSecrets, secretHint, secretWhere, vaultSummary } from "./connectorLibrary";
import { confirmDialog } from "../../ui/dialog";

type Kind = "api_key" | "login" | "env";
/** fixed：给已有环境变量换值（名字锁定，同名保存 = 覆盖）。 */
const EMPTY = { kind: "login" as Kind, name: "", username: "", value: "", hosts: "", header_name: "Authorization", header_prefix: "Bearer ", fixed: false };
const KINDS: { id: Kind; label: string }[] = [{ id: "login", label: "网站登录" }, { id: "api_key", label: "API Key" }, { id: "env", label: "环境变量" }];
const kindIcon = (k: string, size?: number) => (k === "login" ? <IconUser size={size} /> : k === "env" ? <IconTerminal size={size} /> : <IconShield size={size} />);

/** 保险箱：只能存和删，存进去就再也看不到明文。版式同技能/定时任务页（页头摘要 → 起步卡 → 分组带数量 → 错峰进场）。
 *  网站登录 → 云浏览器里代填；API Key → 按域名进请求头；环境变量 → 注入电脑上的命令（后端 app/command_env.py）。三类严格分开使用。 */
export default function VaultScreen() {
  const secrets = useResource<VaultSecret>("/api/vault");
  const [draft, setDraft] = useState<typeof EMPTY | null>(null);
  const [advanced, setAdvanced] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const save = async () => {
    if (!draft) return;
    setErr(null);
    try {
      if (draft.kind === "env") {
        await secrets.create({ kind: "env", name: envName(draft.name), value: draft.value } as never);
        await secrets.reload(); // 同名是覆盖：服务器已删旧条目，重拉免得列表出现两条
      } else {
        await secrets.create({ ...draft, hosts: draft.hosts.split(/[\s,，]+/).filter(Boolean) } as never);
      }
      setDraft(null);
    } catch (e) { setErr(e instanceof Error ? e.message : "保存失败"); }
  };
  const isLogin = draft?.kind === "login";
  const isEnv = draft?.kind === "env";
  const nameErr = isEnv && draft.name.trim() ? envNameError(draft.name) : null;
  const valid = draft && (isEnv
    ? draft.name.trim() && !nameErr && draft.value.length >= ENV_VALUE_MIN && !/[\r\n]/.test(draft.value)
    : draft.name.trim() && draft.value.length >= 4 && draft.hosts.trim() && (!isLogin || draft.username.trim()));

  const start = (kind: Kind, name = "") => { setDraft({ ...EMPTY, kind, name, fixed: !!name }); setAdvanced(false); setErr(null); };
  const remove = async (s: VaultSecret) => {
    if (await confirmDialog({ title: `删除「${s.name}」？`, text: "用到它的任务会拿不到这把钥匙，直到你重新存入。" })) void secrets.remove(s.id);
  };
  const g = groupSecrets(secrets.items);
  let n = 0;
  const rows = (items: VaultSecret[]) => (
    <div className="list">
      {items.map((s) => {
        const hint = secretHint(s);
        return (
          <div key={s.id} className="row enter" style={stagger(++n)}>
            <span className="row-icon">{kindIcon(s.kind)}</span>
            <div className="row-body">
              <div className="row-title">{s.name}</div>
              <div className="row-sub">{secretWhere(s)}</div>
            </div>
            {hint && <span className="row-hint">{hint}</span>}
            <Menu trigger={<IconMore />} label={`${s.name} 的操作`} items={[
              ...(s.kind === "env" ? [{ label: "换个值", icon: <IconEdit />, onSelect: () => start("env", s.name) }] : []),
              { label: "删除", icon: <IconTrash />, danger: true, onSelect: () => void remove(s) }]} />
          </div>
        );
      })}
    </div>
  );

  return (
    <Page header={<PageHeader title="保险箱" back action={
      <button className="icon-btn" onClick={() => start("login")} aria-label="存入"><IconPlus /></button>} />}>
      <PageIntro loading={secrets.loading} summary={vaultSummary(secrets.items)}
        line="加密存在你自己的服务器上，只用于你指定的网站或你电脑上的命令。我只知道“有这把钥匙”，回复里永远看不到内容。" />
      {secrets.loading ? <Skeleton /> : (
        <>
          {secrets.items.length === 0 && (
            <StarterCard title="保险箱是空的" text="存一个网站登录，我在云浏览器里能替你登录；存一个 API Key，我就能调用那个服务；存一个环境变量，你电脑上的程序就能读到它。">
              {SECRET_KINDS.map((k) => (
                <button key={k.kind} className="btn btn-ghost" onClick={() => start(k.kind)}>
                  {kindIcon(k.kind, 16)}{k.label}</button>
              ))}
            </StarterCard>
          )}
          {g.logins.length > 0 && <Section title={`网站登录 · ${g.logins.length}`}>{rows(g.logins)}</Section>}
          {g.keys.length > 0 && <Section title={`API Key · ${g.keys.length}`}>{rows(g.keys)}</Section>}
          {g.envs.length > 0 && <Section title={`环境变量 · ${g.envs.length}`}>{rows(g.envs)}</Section>}
        </>
      )}
      {draft && (
        <Sheet title={draft.fixed ? `给 $${draft.name} 换个值` : "存进保险箱"} onClose={() => setDraft(null)} actions={<>
          <button className="btn btn-ghost" onClick={() => setDraft(null)}>取消</button>
          <button className="btn btn-primary" disabled={!valid} onClick={save}>加密保存</button>
        </>}>
          {!draft.fixed && <div className="segmented">
            {KINDS.map((k) => <button key={k.id} className={draft.kind === k.id ? "on" : ""} onClick={() => setDraft({ ...draft, kind: k.id })}>{k.label}</button>)}
          </div>}
          {isEnv ? (
            <div key="env" className="fade-swap">
              <label className="form-field"><span>变量名</span>
                <input className="mono" value={draft.name} disabled={draft.fixed} onChange={(e) => setDraft({ ...draft, name: e.target.value })}
                  placeholder="TELEGRAM_BOT_TOKEN" autoCapitalize="characters" autoComplete="off" spellCheck={false} />
                {nameErr ? <small className="form-error">{nameErr}</small> : null}</label>
              <label className="form-field"><span>值</span>
                <input type="password" autoComplete="off" value={draft.value} onChange={(e) => setDraft({ ...draft, value: e.target.value })} placeholder="保存后不会再显示" />
                <small>只注入你电脑上跑的命令（含后台、常驻、定时脚本），输出里显示成 [$名字]；常驻程序重启后用新值。至少 {ENV_VALUE_MIN} 个字符。</small></label>
            </div>
          ) : <div key="site" className="fade-swap">
            <label className="form-field"><span>名称</span>
              <input value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} placeholder={isLogin ? "淘宝" : "GitHub Token"} /></label>
            {isLogin && <label className="form-field"><span>用户名 / 手机号 / 邮箱</span>
              <input value={draft.username} onChange={(e) => setDraft({ ...draft, username: e.target.value })} autoCapitalize="off" autoComplete="off" /></label>}
            <label className="form-field"><span>{isLogin ? "密码" : "密钥"}</span>
              <input type="password" autoComplete="off" value={draft.value} onChange={(e) => setDraft({ ...draft, value: e.target.value })} placeholder="保存后不会再显示" /></label>
            <label className="form-field"><span>{isLogin ? "网站域名" : "只用于这些域名"}</span>
              <input value={draft.hosts} onChange={(e) => setDraft({ ...draft, hosts: e.target.value })} placeholder={isLogin ? "taobao.com" : "api.github.com"} autoCapitalize="off" />
              <small>多个用逗号隔开，子域名自动包含。发往其他网站的请求不会带上它。</small></label>
            {isLogin ? null : advanced ? (
              <div className="form-grid">
                <label className="form-field"><span>请求头</span>
                  <input value={draft.header_name} onChange={(e) => setDraft({ ...draft, header_name: e.target.value })} /></label>
                <label className="form-field"><span>前缀</span>
                  <input value={draft.header_prefix} onChange={(e) => setDraft({ ...draft, header_prefix: e.target.value })} /></label>
              </div>
            ) : <button className="text-link" onClick={() => setAdvanced(true)}>高级：自定义请求头</button>}
          </div>}
          {err && <div className="error-banner">{err}</div>}
        </Sheet>
      )}
    </Page>
  );
}
