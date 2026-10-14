import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { auth, http, notifyUnauthorized, server } from "../../lib/api";
import { outbox } from "../../lib/outbox";
import { budgetLevel, budgetRatio, formatMoney, formatTokens, type UsageReport } from "../../lib/usage";
import { IconBack, IconCard, IconClock, IconComputer, IconDoc, IconFeedback, IconPlug, IconSettings, IconShield, IconUser } from "../../ui/icons";
import { stagger } from "../../ui/kit";
import CountUp from "../../ui/CountUp";
import { MeRows, type MeRow } from "./meRows";
import { useServerVersion } from "../../hooks/useServerVersion";
import { clientOutdated } from "../../lib/version";
import "./me.css";

/** v2.81 按 docs/home-redesign.md B 做减法（= App me_screen.dart）：两组行，每行只有 图标 + 标题 + 箭头。 */
const GROUP1: MeRow[] = [
  { to: "/me/profile", icon: IconUser, title: "个人资料" },
  { to: "/me/tasks", icon: IconClock, title: "定时任务" },
  { to: "/me/accounts", icon: IconPlug, title: "账户" },
  { to: "/me/wallet", icon: IconCard, title: "钱包" },
  { to: "/me/computer", icon: IconComputer, title: "我的电脑" },
];
const GROUP2: MeRow[] = [
  { to: "/me/security", icon: IconShield, title: "安全" },
  { to: "/me/preferences", icon: IconSettings, title: "偏好设置" },
  { to: "/me/feedback", icon: IconFeedback, title: "反馈" },
  { to: "/me/about", icon: IconDoc, title: "关于" },
];

/** 用量卡（像 Hark 方案卡）：左边一行“本月 ¥12.30”（没配单价是 token），有预算多一条细进度条；右边“查看用量”。 */
function UsageSummary() {
  const [r, setR] = useState<UsageReport | null>(null);
  const load = useCallback(() => { http.get<UsageReport>("/api/usage").then(setR).catch(() => setR(null)); }, []);
  useEffect(load, [load]);
  const money = !!r && r.priced.length > 0;
  const ratio = r ? budgetRatio(r) : null;
  return (
    <div className="glass-card me-usage enter" style={stagger(1)}>
      <div className="me-usage-row">
        <span className="me-usage-label">本月</span>
        <span className="me-usage-value"><CountUp value={!r ? "—" : money ? formatMoney(r.month.cost, r.currency) : `${formatTokens(r.month.tokens)} token`} /></span>
        {r?.budget != null && money && <span className="me-usage-budget">/ {formatMoney(r.budget, r.currency)}</span>}
        <Link className="pill primary me-usage-go" to="/me/usage">查看用量</Link>
      </div>
      {r && ratio !== null && (
        <div className={`meter meter-${budgetLevel(r)} thin`} role="meter" aria-label="本月预算" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(ratio * 100)}>
          <span style={{ transform: `scaleX(${Math.min(ratio, 1)})` }} />
        </div>
      )}
    </div>
  );
}

/** 页头：名字大字 + 域名小字（GET /api/auth/me；= App _Identity）。没取到（加载中 / 老服务器）写“我的”，取到后淡入。 */
function Identity() {
  const [name, setName] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    http.get<{ username?: string }>("/api/auth/me")
      .then((j) => { if (live) setName(j.username?.trim() || null); })
      .catch(() => {});
    return () => { live = false; };
  }, []);
  const raw = server.get() || location.origin;
  let host = raw;
  try { host = new URL(raw).host || raw; } catch { /* 不是完整 URL 就原样显示 */ }
  return (
    <div className="me-id" aria-label={name ? `已登录 ${name}，服务器 ${host}` : `服务器 ${host}`}>
      <h1 key={name ?? ""} className={name ? "fade-in" : undefined}>{name ?? "我的"}</h1>
      <div className="me-server">{host}</div>
    </div>
  );
}

/** “我的”（v2.81 一屏）：页头一行（返回 + 名字/域名）→ 用量卡 → 两组行 → 退出登录胶囊。外观、头像颜色、回复语言都在“偏好设置”。 */
export default function MeScreen() {
  const nav = useNavigate();
  // 从站内点头像进来 → 返回上一页；直接打开（深链接 / 刷新）→ 回到主页
  const root = !((window.history.state as { idx?: number } | null)?.idx);
  // v2.61：先让服务器作废这个 token（登录设备里就没了这台），失败不拦
  const outdated = clientOutdated(useServerVersion());
  const logout = async () => { await http.post("/api/auth/logout", {}).catch(() => {}); auth.clear(); outbox.clear(); notifyUnauthorized(); };
  return (
    <div className="page me">
      <div className="page-inner">
        <div className="me-head enter">
          <button className="glass-btn glass" onClick={() => (root ? nav("/") : nav(-1))} aria-label={root ? "回到主页" : "返回"} title={root ? "回到主页" : "返回"}><IconBack /></button>
          <Identity />
        </div>
        <UsageSummary />
        <div className="enter me-group" style={stagger(2)}><MeRows rows={GROUP1} /></div>
        <div className="enter me-group" style={stagger(3)}><MeRows rows={GROUP2.map((r) => (r.to === "/me/about" && outdated ? { ...r, value: "请更新" } : r))} /></div>
        <div className="me-logout enter" style={stagger(4)}>
          <button className="pill" onClick={() => void logout()}>退出登录</button>
        </div>
      </div>
    </div>
  );
}
