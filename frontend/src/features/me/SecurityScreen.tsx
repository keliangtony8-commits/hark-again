import { useState } from "react";
import { useSwr } from "../../hooks/useSwr";
import { auth, http } from "../../lib/api";
import { enabledSignedOutToast } from "../../lib/loginSessions";
import {
  RECOVERY_LOW, cleanCode, looksLikeTotp, qrDrawable, qrPath, recoveryCodesText, recoveryLine, twoFactorSummary,
  type TwoFactorSetup, type TwoFactorStatus,
} from "../../lib/twoFactor";
import CopyButton from "../../ui/CopyButton";
import { IconKey, IconLock, IconShield } from "../../ui/icons";
import { ListGroup, ListRow, Page, PageHeader, PageIntro, Section, Sheet, Skeleton, Spot } from "../../ui/kit";
import LoginSessions from "./LoginSessions";

/** 安全（v2.58，= App features/me/security_screen.dart；对标 Hark 设置 → 安全 → 两步验证）。
 *  版式同保险箱：页头摘要 + 一句说明 → 一组行。打开：扫码（电脑上用手机扫）→ 回填 6 位码 → 一次性展示恢复码；
 *  关闭 / 重新生成恢复码要密码 + 一个码（错了服务器回 403，不会把你登出）。
 *  v2.61：打开时服务器顺手退出其他所有设备（恢复码弹层写明几台）；下面一节“登录设备”在 LoginSessions.tsx。 */
type Ask = { kind: "disable" | "recovery" } | null;

export default function SecurityScreen() {
  const { data: s, error, reload, mutate: setS } = useSwr<TwoFactorStatus>("/api/auth/2fa");
  const err = error ? error.message || "读不到安全设置" : null;
  const load = () => void reload();
  const [setup, setSetup] = useState<TwoFactorSetup | null>(null);
  const [codes, setCodes] = useState<{ list: string[]; title: string; account: string; note?: string | null } | null>(null);
  const [devicesKey, setDevicesKey] = useState(0);
  const [ask, setAsk] = useState<Ask>(null);
  const [note, setNote] = useState<string | null>(null);

  const start = async () => {
    setNote(null);
    try { setSetup(await http.post<TwoFactorSetup>("/api/auth/2fa/setup", {})); }
    catch (e) { setNote(e instanceof Error ? e.message : "没打开"); }
  };

  return (
    <Page header={<PageHeader title="安全" back />}>
      <PageIntro loading={!s && !err} summary={s ? twoFactorSummary(s) : ""}
        line={s?.enabled
          ? "登录时除了密码，还要验证器 App 里的 6 位码；手机丢了用恢复码。"
          : "打开后，登录要多填验证器 App（Google Authenticator、Microsoft Authenticator 等）里的 6 位码。密码泄露了，别人也进不来。"} />
      {note && <div className="notice ok" role="status" onClick={() => setNote(null)}>{note}</div>}
      {err ? (
        <div className="error-banner">{err} <button className="text-link" onClick={load}>重试</button></div>
      ) : !s ? <Skeleton rows={2} /> : (
        <Section enter={1}>
          <ListGroup key={String(s.enabled)} className="fade-swap">
            {!s.enabled ? (
              <ListRow spot="two-factor" onClick={start} icon={<IconShield />} title="打开两步验证"
                sub={s.pending ? "上次没设置完，重新扫一次码" : "大约一分钟，需要一个验证器 App"} />
            ) : (<>
              <ListRow spot="two-factor" icon={<IconLock />} title="两步验证"
                sub={s.enabled_at ? `${new Date(s.enabled_at).toLocaleDateString("zh-CN")} 打开` : "已开"} />
              <ListRow onClick={() => setAsk({ kind: "recovery" })} icon={<IconKey />} title="恢复码"
                sub={<>{s.recovery_left <= RECOVERY_LOW && <span className="warn-text">{s.recovery_left === 0 ? "用完了" : "快用完了"} · </span>}{recoveryLine(s.recovery_left)}</>} />
              <ListRow onClick={() => setAsk({ kind: "disable" })} trail={null} icon={<IconShield />}
                title={<span className="danger-text">关闭两步验证</span>} sub="需要密码和一个验证码" />
            </>)}
          </ListGroup>
        </Section>
      )}
      <Spot id="sessions"><LoginSessions enter={2} reloadKey={devicesKey} onNote={setNote} /></Spot>
      {setup && <SetupSheet setup={setup} onClose={() => { setSetup(null); load(); }}
        onDone={(r) => {
          if (r.token) auth.set(r.token); // 本机是升级前的老登录：服务器换发了新 token
          setSetup(null); load(); setDevicesKey((k) => k + 1);
          setCodes({ list: r.recovery_codes, title: "两步验证已打开", account: setup.account, note: enabledSignedOutToast(r.signed_out ?? 0) });
        }} />}
      {codes && <CodesSheet {...codes} onClose={() => setCodes(null)} />}
      {ask && <ConfirmSheet kind={ask.kind} onClose={() => setAsk(null)} onDone={(r) => {
        const { recovery_codes, ...status } = r; // 恢复码只进弹层，不进缓存
        setAsk(null); setS(status);
        if (ask.kind === "disable") setNote("两步验证已关闭");
        else if (recovery_codes) setCodes({ list: recovery_codes, title: "新的恢复码", account: "" });
      }} />}
    </Page>
  );
}

type Enabled = { recovery_codes: string[]; signed_out?: number; token?: string };

function SetupSheet({ setup, onClose, onDone }: { setup: TwoFactorSetup; onClose: () => void; onDone: (r: Enabled) => void }) {
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const submit = async () => {
    setBusy(true); setErr(null);
    try { onDone(await http.post<Enabled>("/api/auth/2fa/enable", { code: cleanCode(code) })); }
    catch (e) { setErr(e instanceof Error ? e.message : "没打开"); }
    finally { setBusy(false); }
  };
  const ready = looksLikeTotp(code) && !busy;
  return (
    <Sheet title="打开两步验证" onClose={onClose} actions={<>
      <button className="btn btn-ghost" onClick={onClose}>取消</button>
      <button className="btn btn-primary" disabled={!ready} onClick={submit}>{busy ? "确认中…" : "确认并打开"}</button>
    </>}>
      <p className="row-sub wrap">① 用手机上的验证器 App 扫这个码（在手机上打开本页时，直接点“在这台设备上添加”）</p>
      {qrDrawable(setup.qr) && <QrCode rows={setup.qr} />}
      <div className="tf-actions"><a className="btn btn-ghost" href={setup.uri}>在这台设备上添加</a></div>
      <div className="tf-secret"><div><small>或手动输入秘钥</small><code className="mono">{setup.secret}</code></div>
        <CopyButton text={setup.secret.replace(/ /g, "")} label="复制秘钥" /></div>
      <label className="form-field"><span>② 填验证器里显示的 6 位码</span>
        <input value={code} onChange={(e) => setCode(e.target.value)} inputMode="numeric" autoComplete="one-time-code" maxLength={7} autoFocus
          onKeyDown={(e) => { if (e.key === "Enter" && ready) void submit(); }} /></label>
      {err && <div className="error-banner">{err}</div>}
    </Sheet>
  );
}

/** 二维码：服务器给模块矩阵，这里画成一条 SVG path。永远黑码白底（--qr-dark / --qr-light）。 */
export function QrCode({ rows, quiet = 2 }: { rows: string[]; quiet?: number }) {
  const n = rows.length + quiet * 2;
  return (
    <svg className="tf-qr enter" viewBox={`0 0 ${n} ${n}`} role="img" aria-label="两步验证二维码" shapeRendering="crispEdges">
      <rect width={n} height={n} fill="var(--qr-light)" />
      <path d={qrPath(rows, quiet)} fill="var(--qr-dark)" />
    </svg>
  );
}

function CodesSheet({ list, title, account, note, onClose }: { list: string[]; title: string; account: string; note?: string | null; onClose: () => void }) {
  return (
    <Sheet title={title} onClose={onClose} actions={<>
      <CopyButton text={recoveryCodesText(list, account)} label="复制全部" />
      <button className="btn btn-primary" onClick={onClose}>我已存好</button>
    </>}>
      <p className="row-sub wrap">把这些恢复码存到安全的地方（密码管理器、纸上）。手机丢了时，每个能代替验证码登录一次。关掉后不会再显示。</p>
      {note && <p className="row-sub wrap">{note}</p>}
      <div className="tf-codes">{list.map((c, i) => <code key={c} className="mono enter" style={{ animationDelay: `${i * 30}ms` }}>{c}</code>)}</div>
    </Sheet>
  );
}

type Result = TwoFactorStatus & { recovery_codes?: string[] };

function ConfirmSheet({ kind, onClose, onDone }: { kind: "disable" | "recovery"; onClose: () => void; onDone: (r: Result) => void }) {
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const disable = kind === "disable";
  const submit = async () => {
    setBusy(true); setErr(null);
    try { onDone(await http.post<Result>(disable ? "/api/auth/2fa/disable" : "/api/auth/2fa/recovery", { password, code: cleanCode(code) })); }
    catch (e) { setErr(e instanceof Error ? e.message : "操作失败"); }
    finally { setBusy(false); }
  };
  return (
    <Sheet title={disable ? "关闭两步验证" : "重新生成恢复码"} onClose={onClose} actions={<>
      <button className="btn btn-ghost" onClick={onClose}>取消</button>
      <button className={disable ? "btn btn-danger-fill" : "btn btn-primary"} disabled={!password || !cleanCode(code) || busy} onClick={submit}>{disable ? "关闭" : "生成"}</button>
    </>}>
      <p className="row-sub wrap">{disable ? "关掉后登录只要密码。" : "旧的恢复码会全部作废。"}</p>
      <label className="form-field"><span>当前密码</span>
        <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" autoFocus /></label>
      <label className="form-field"><span>验证码或恢复码</span>
        <input value={code} onChange={(e) => setCode(e.target.value)} autoComplete="one-time-code" placeholder="6 位数字，或 xxxx-xxxx" /></label>
      {err && <div className="error-banner">{err}</div>}
    </Sheet>
  );
}
