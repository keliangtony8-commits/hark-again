import { useState } from "react";
import type { VaultSecret } from "../../lib/types";
import { withRetried } from "../../lib/taskLabels";
import { IconEdit, IconMore, IconShield, IconTerminal, IconTrash, IconUser } from "../../ui/icons";
import { Menu, Sheet, stagger } from "../../ui/kit";
import { ENV_VALUE_MIN, envName, envNameError, secretHint, secretWhere } from "./connectorLibrary";
import { confirmDialog } from "../../ui/dialog";
import type { useResource } from "../../hooks/useResource";

/** 加密保存的三类（网站登录 → 云浏览器里代填；API Key → 按域名进请求头；环境变量 → 注入电脑上的命令，后端 app/command_env.py）：
 *  存入弹层 + 列表行。页面只有“连接的账号”一页（ConnectorsScreen，v2.96 保险箱页并入；= App secret_rows.dart）。 */
export type SecretKind = "api_key" | "login" | "env";
export type SecretDraftStart = { kind: SecretKind; name?: string };
type Secrets = ReturnType<typeof useResource<VaultSecret>>;
/** fixed：给已有环境变量换值（名字锁定，同名保存 = 覆盖）。 */
const EMPTY = { kind: "login" as SecretKind, name: "", username: "", value: "", hosts: "", header_name: "Authorization", header_prefix: "Bearer ", fixed: false };
/** 种类在“添加什么？”里已经选过（= App 各自的表单标题），弹层里不再放切换。 */
const TITLES: Record<SecretKind, string> = { login: "新网站登录", api_key: "新 API Key", env: "新环境变量" };
export const secretKindIcon = (k: string, size?: number) => (k === "login" ? <IconUser size={size} /> : k === "env" ? <IconTerminal size={size} /> : <IconShield size={size} />);

/** 一组密钥行；from = 整页错峰序号的起点，返回用掉之后的序号由调用方自己累加。 */
export function SecretRows({ items, secrets, onEdit, from }: { items: VaultSecret[]; secrets: Secrets; onEdit: (s: SecretDraftStart) => void; from: number }) {
  const remove = async (s: VaultSecret) => {
    if (await confirmDialog({ title: `删除「${s.name}」？`, text: "用到它的任务会拿不到这把钥匙，直到你重新存入。" })) void secrets.remove(s.id);
  };
  return (
    <div className="list">
      {items.map((s, i) => {
        const hint = secretHint(s);
        return (
          <div key={s.id} className="row enter" style={stagger(from + i)}>
            <span className="row-icon">{secretKindIcon(s.kind)}</span>
            <div className="row-body">
              <div className="row-title">{s.name}</div>
              <div className="row-sub">{secretWhere(s)}</div>
            </div>
            {hint && <span className="row-hint">{hint}</span>}
            <Menu trigger={<IconMore />} label={`${s.name} 的操作`} items={[
              ...(s.kind === "env" ? [{ label: "换个值", icon: <IconEdit />, onSelect: () => onEdit({ kind: "env", name: s.name }) }] : []),
              { label: "删除", icon: <IconTrash />, danger: true, onSelect: () => void remove(s) }]} />
          </div>
        );
      })}
    </div>
  );
}

/** 存入弹层：start.kind 决定先显示哪类，start.name = 给已有环境变量换值。onSaved 收到那一句提示（带 v2.19 “已重新运行”）。 */
export default function SecretSheet({ start, secrets, onClose, onSaved }: { start: SecretDraftStart; secrets: Secrets; onClose: () => void; onSaved: (text: string) => void }) {
  const [draft, setDraft] = useState({ ...EMPTY, kind: start.kind, name: start.name ?? "", fixed: !!start.name });
  const [advanced, setAdvanced] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const save = async () => {
    setErr(null);
    try {
      if (draft.kind === "env") {
        await secrets.create({ kind: "env", name: envName(draft.name), value: draft.value } as never);
        await secrets.reload(); // 同名是覆盖：服务器已删旧条目，重拉免得列表出现两条
        onSaved(`已加密保存「$${envName(draft.name)}」`);
      } else {
        const x = await secrets.create({ ...draft, hosts: draft.hosts.split(/[\s,，]+/).filter(Boolean) } as never);
        onSaved(withRetried(`已加密保存「${x.name}」`, x.retried_note));
      }
      onClose();
    } catch (e) { setErr(e instanceof Error ? e.message : "保存失败"); }
  };
  const isLogin = draft.kind === "login";
  const isEnv = draft.kind === "env";
  const nameErr = isEnv && draft.name.trim() ? envNameError(draft.name) : null;
  const valid = isEnv
    ? draft.name.trim() && !nameErr && draft.value.length >= ENV_VALUE_MIN && !/[\r\n]/.test(draft.value)
    : draft.name.trim() && draft.value.length >= 4 && draft.hosts.trim() && (!isLogin || draft.username.trim());

  return (
    <Sheet title={draft.fixed ? `给 $${draft.name} 换个值` : TITLES[draft.kind]} onClose={onClose} actions={<>
      <button className="btn btn-ghost" onClick={onClose}>取消</button>
      <button className="btn btn-primary" disabled={!valid} onClick={save}>加密保存</button>
    </>}>
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
  );
}
