import { useState } from "react";
import { useResource } from "../../hooks/useResource";
import type { VaultSecret } from "../../lib/types";
import { IconPlus, IconShield } from "../../ui/icons";
import { Hint, Page, PageHeader, Sheet, Skeleton } from "../../ui/kit";
import { confirmDialog } from "../../ui/dialog";

type Kind = "api_key" | "login";
const EMPTY = { kind: "login" as Kind, name: "", username: "", value: "", hosts: "", header_name: "Authorization", header_prefix: "Bearer " };
const KINDS: { id: Kind; label: string }[] = [{ id: "login", label: "网站登录" }, { id: "api_key", label: "API Key" }];

/** 保险箱：只能存和删，存进去就再也看不到明文。
 *  网站登录 → 云浏览器里代填；API Key → 按域名进请求头。两类严格分开使用。 */
export default function VaultScreen() {
  const secrets = useResource<VaultSecret>("/api/vault");
  const [draft, setDraft] = useState<typeof EMPTY | null>(null);
  const [advanced, setAdvanced] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const save = async () => {
    if (!draft) return;
    setErr(null);
    try {
      await secrets.create({ ...draft, hosts: draft.hosts.split(/[\s,，]+/).filter(Boolean) } as never);
      setDraft(null);
    } catch (e) { setErr(e instanceof Error ? e.message : "保存失败"); }
  };
  const isLogin = draft?.kind === "login";
  const valid = draft && draft.name.trim() && draft.value.length >= 4 && draft.hosts.trim() && (!isLogin || draft.username.trim());

  return (
    <Page header={<PageHeader title="保险箱" back action={
      <button className="icon-btn" onClick={() => { setDraft(EMPTY); setAdvanced(false); }} aria-label="添加"><IconPlus /></button>} />}>
      <p className="desc">加密存在你自己的服务器上，只用于你指定的网站。我只知道“有这把钥匙”，永远看不到内容。</p>
      {secrets.loading ? <Skeleton /> : secrets.items.length === 0 ? (
        <Hint icon={<IconShield size={26} />} title="保险箱是空的"
          text="存一个网站登录，我在云浏览器里能替你登录；存一个 API Key，我就能调用那个服务。"
          action={<button className="btn btn-primary" onClick={() => setDraft(EMPTY)}><IconPlus />添加</button>} />
      ) : (
        <div className="list">
          {secrets.items.map((s) => (
            <div key={s.id} className="row">
              <span className="row-icon"><IconShield /></span>
              <div className="row-body">
                <div className="row-title">{s.name}</div>
                <div className="row-sub">{s.kind === "login" ? `登录 · ${s.username}` : `API Key · ••••${s.preview}`} · {s.hosts.join("、")}</div>
              </div>
              <button className="btn btn-danger btn-sm" onClick={async () => { if (await confirmDialog({ title: `删除「${s.name}」？`, text: "用到它的任务会拿不到这把钥匙。" })) void secrets.remove(s.id); }}>删除</button>
            </div>
          ))}
        </div>
      )}
      {draft && (
        <Sheet title="存进保险箱" onClose={() => setDraft(null)} actions={<>
          <button className="btn btn-ghost" onClick={() => setDraft(null)}>取消</button>
          <button className="btn btn-primary" disabled={!valid} onClick={save}>加密保存</button>
        </>}>
          <div className="segmented">
            {KINDS.map((k) => <button key={k.id} className={draft.kind === k.id ? "on" : ""} onClick={() => setDraft({ ...draft, kind: k.id })}>{k.label}</button>)}
          </div>
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
          {err && <div className="error-banner">{err}</div>}
        </Sheet>
      )}
    </Page>
  );
}
