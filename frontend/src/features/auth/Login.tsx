import { useState } from "react";
import BrandMark from "../../ui/BrandMark";
import { ApiError, api, auth, server } from "../../lib/api";
import { cleanCode } from "../../lib/twoFactor";
import "../../ui/ui.css";
import "../../ui/glass.css";
import "./login.css";

// 浏览器里访问时同源即可；安卓 App 需要填服务器地址
const isNativeApp = location.protocol === "capacitor:" || location.hostname === "localhost" && !location.port;

export default function Login({ onDone }: { onDone: () => void }) {
  const [srv, setSrv] = useState(server.get());
  const [username, setU] = useState("");
  const [password, setP] = useState("");
  const [code, setCode] = useState("");
  const [needCode, setNeedCode] = useState(false); // v2.58：服务器回 428 = 开着两步验证，展开验证码框
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [showServer, setShowServer] = useState(isNativeApp || !!server.get());

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true); setErr(null);
    server.set(srv.trim());
    try { auth.set((await api.login(username, password, needCode ? cleanCode(code) : undefined)).token); onDone(); }
    catch (e) {
      if (e instanceof ApiError && e.status === 428) setNeedCode(true);
      else setErr(e instanceof Error ? e.message : "登录失败");
    }
    finally { setBusy(false); }
  };

  return (
    <div className="login">
      <form className="login-card glass" onSubmit={submit}>
        <div className="brand"><BrandMark size={28} />Assistant</div>
        <h1>欢迎回来</h1>
        <p>登录你的私人助手</p>
        {showServer && <label className="form-field"><input placeholder="服务器地址，如 https://ai.example.com" value={srv}
          onChange={(e) => { setSrv(e.target.value); setNeedCode(false); }} inputMode="url" autoCapitalize="off" /></label>}
        <label className="form-field"><input placeholder="用户名" value={username} onChange={(e) => { setU(e.target.value); setNeedCode(false); }} autoComplete="username" autoCapitalize="off" /></label>
        <label className="form-field"><input placeholder="密码" type="password" value={password} onChange={(e) => setP(e.target.value)} autoComplete="current-password" /></label>
        {needCode && <div className="login-code fade-swap">
          <p>这个账号开了两步验证，填验证器里的 6 位码；手机不在身边就填一个恢复码。</p>
          <label className="form-field"><input placeholder="验证码" value={code} onChange={(e) => setCode(e.target.value)}
            autoComplete="one-time-code" autoCapitalize="off" autoFocus /></label>
        </div>}
        <button className="btn btn-primary btn-block" disabled={busy || !username || !password || (needCode && cleanCode(code).length < 6) || (showServer && isNativeApp && !srv)}>{busy ? "登录中…" : "登录"}</button>
        {err && <div className="login-error">{err}</div>}
        {!showServer && <button type="button" className="login-link" onClick={() => setShowServer(true)}>连接其他服务器</button>}
      </form>
    </div>
  );
}
