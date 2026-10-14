import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { auth, http, notifyUnauthorized, server } from "../../lib/api";
import { setSolid, useLook } from "../../lib/look";
import { outbox } from "../../lib/outbox";
import { APPEARANCES, setAppearance, useAppearance } from "../../lib/theme";
import { feedbackRowSubtitle, type FeedbackList } from "../../lib/feedback";
import { twoFactorRowSubtitle, type TwoFactorStatus } from "../../lib/twoFactor";
import { budgetLevel, budgetRatio, formatMoney, formatTokens, type UsageReport } from "../../lib/usage";
import { Avatar } from "../../ui/glass";
import { IconBack, IconBrain, IconCard, IconChevron, IconClock, IconComputer, IconFeedback, IconLayout, IconLock, IconPlug, IconShield, IconSpark } from "../../ui/icons";
import { Section, Segmented, Toggle, stagger } from "../../ui/kit";
import CountUp from "../../ui/CountUp";
import AvatarColorPop from "./AvatarColorPop";
import ReplyLanguageRow from "./ReplyLanguageRow";
import "./me.css";

const GROUPS = [
  { title: "了解你", items: [
    { to: "/me/memory", icon: IconBrain, title: "记忆", sub: "我记住的偏好和事实，随时可改可删" },
    { to: "/me/tasks", icon: IconClock, title: "定时任务", sub: "每天的简报、提醒和例行检查" },
    { to: "/me/skills", icon: IconSpark, title: "技能", sub: "内置和你自定义的做事方法" },
    { to: "/me/computer", icon: IconComputer, title: "我的电脑", sub: "云端 Linux 的状态、后台任务和文件" },
    { to: "/me/pages", icon: IconLayout, title: "Pages", sub: "我为你做的可分享网页" },
  ] },
  { title: "连接", items: [
    { to: "/me/connectors", icon: IconPlug, title: "连接器", sub: "Gmail、日历、GitHub 和 MCP 服务器" },
    { to: "/me/vault", icon: IconShield, title: "保险箱", sub: "加密保存的登录和密钥，模型看不到明文" },
    { to: "/me/wallet", icon: IconCard, title: "钱包", sub: "付款卡，结账时替你填，付款前先问你" },
  ] },
  { title: "安全", items: [
    { to: "/me/security", icon: IconLock, title: "两步验证", sub: "" }, // 副标题按状态（twoFactorRowSubtitle）
    { to: "/me/feedback", icon: IconFeedback, title: "反馈", sub: "" }, // 副标题按未解决条数（feedbackRowSubtitle）
  ] },
];

/** 用量卡：本月花费 / 预算 + 一条细进度条 + “查看用量”。没配单价时显示 token。 */
function UsageSummary() {
  const [r, setR] = useState<UsageReport | null>(null);
  const load = useCallback(() => { http.get<UsageReport>("/api/usage").then(setR).catch(() => setR(null)); }, []);
  useEffect(load, [load]);
  const money = !!r && r.priced.length > 0;
  const ratio = r ? budgetRatio(r) : null;
  return (
    <div className="glass-card me-usage enter" style={stagger(1)}>
      <div className="tile-label">本月花费</div>
      <div className="me-usage-row">
        <div className="tile-value"><CountUp value={!r ? "—" : money ? formatMoney(r.month.cost, r.currency) : `${formatTokens(r.month.tokens)} token`} /></div>
        {r?.budget != null && money && <div className="me-usage-budget">/ {formatMoney(r.budget, r.currency)}</div>}
      </div>
      {r && ratio !== null && (
        <div className={`meter meter-${budgetLevel(r)} thin`} role="meter" aria-label="本月预算" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(ratio * 100)}>
          <span style={{ transform: `scaleX(${Math.min(ratio, 1)})` }} />
        </div>
      )}
      <div className="pills"><Link className="pill" to="/me/usage">查看用量</Link></div>
    </div>
  );
}

/** 页头身份行：“用户名 · 域名”（GET /api/auth/me）。没取到（加载中 / 老服务器）只显示域名；取到后淡入（= App _Identity）。 */
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
    <div className="me-server" aria-label={name ? `已登录 ${name}，服务器 ${host}` : `服务器 ${host}`}>
      {name && <span key={name} className="me-name fade-in">{name}<span className="me-dot" aria-hidden="true">·</span></span>}
      <span>{host}</span>
    </div>
  );
}

/** “我的”（设计 v2）：不是栏目，点顶栏头像进来。大头像（点开换颜色）+ 用量卡 + 分组列表 + 外观与偏好 + 退出登录。 */
export default function MeScreen() {
  const nav = useNavigate();
  const appearance = useAppearance();
  const { solid } = useLook();
  const [pop, setPop] = useState(false);
  const hero = useRef<HTMLDivElement>(null);
  const closePop = useCallback(() => setPop(false), []);
  // 从站内点头像进来 → 返回上一页；直接打开（深链接 / 刷新）→ 回到主页
  const root = !((window.history.state as { idx?: number } | null)?.idx);
  const [tf, setTf] = useState<TwoFactorStatus | null>(null);
  useEffect(() => { http.get<TwoFactorStatus>("/api/auth/2fa").then(setTf).catch(() => setTf(null)); }, []);
  const [fb, setFb] = useState<FeedbackList | null>(null);
  useEffect(() => { http.get<FeedbackList>("/api/feedback").then(setFb).catch(() => setFb(null)); }, []);
  // v2.61：先让服务器作废这个 token（登录设备里就没了这台），失败不拦
  const logout = async () => { await http.post("/api/auth/logout", {}).catch(() => {}); auth.clear(); outbox.clear(); notifyUnauthorized(); };
  return (
    <div className="page me">
      <div className="page-inner">
        <div className="me-top">
          <button className="glass-btn glass" onClick={() => (root ? nav("/") : nav(-1))} aria-label={root ? "回到主页" : "返回"} title={root ? "回到主页" : "返回"}><IconBack /></button>
        </div>
        <div className="me-hero" ref={hero}>
          <Avatar large onClick={() => setPop((v) => !v)} label="换头像颜色" />
          {pop && <AvatarColorPop onClose={closePop} boundary={hero} />}
          <h1>我的</h1>
          <Identity />
        </div>
        <UsageSummary />
        {GROUPS.map((g, i) => (
          <Section key={g.title} title={g.title} enter={i + 2}>
            <div className="list">
              {g.items.map(({ to, icon: Icon, title, sub }) => {
                const inner = <>
                  <span className="row-icon"><Icon /></span>
                  <div className="row-body"><div className="row-title">{title}</div><div className="row-sub">{to === "/me/security" ? twoFactorRowSubtitle(tf) : to === "/me/feedback" ? feedbackRowSubtitle(fb) : sub}</div></div>
                  <span className="row-trail"><IconChevron /></span>
                </>;
                return <Link key={to} to={to} className="row">{inner}</Link>;
              })}
            </div>
          </Section>
        ))}
        <Section title="外观与偏好" enter={GROUPS.length + 2}>
          <div className="list">
            <div className="row me-appearance"><div className="row-body"><div className="row-title">外观</div></div>
              <Segmented label="外观" value={appearance} options={APPEARANCES} onChange={setAppearance} /></div>
            <div className="row"><div className="row-body"><div className="row-title">减少透明度</div><div className="row-sub">玻璃换成实色，不模糊（更省电、更清楚）</div></div>
              <Toggle on={solid} onChange={setSolid} label="减少透明度" /></div>
            <ReplyLanguageRow />
          </div>
        </Section>
        <Section enter={GROUPS.length + 3}>
          <div className="list"><button className="row" onClick={() => void logout()}><div className="row-body"><div className="row-title danger-text">退出登录</div></div></button></div>
        </Section>
      </div>
    </div>
  );
}
