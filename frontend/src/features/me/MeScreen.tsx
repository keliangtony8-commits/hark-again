import { useCallback, useEffect, useState, type ComponentType } from "react";
import { Link, useNavigate } from "react-router-dom";
import { auth, http, notifyUnauthorized, server } from "../../lib/api";
import { outbox } from "../../lib/outbox";
import { budgetLevel, budgetRatio, formatMoney, formatTokens, type UsageReport } from "../../lib/usage";
import { IconCard, IconClock, IconComputer, IconDoc, IconFeedback, IconGauge, IconLogout, IconPlug, IconSearch, IconSettings, IconShield, IconUser } from "../../ui/icons";
import { Highlight, Hint, ListGroup, ListRow, Page, SearchField, Section, stagger } from "../../ui/kit";
import { meLocation, meWhere, searchMe, type MeEntry, type MeSection } from "./meIndex";
import CountUp from "../../ui/CountUp";
import ProfileSheet from "./ProfileSheet";
import { profileName, useProfile } from "../../lib/profile";
import { Avatar } from "../../ui/glass";
import { useServerVersion } from "../../hooks/useServerVersion";
import { clientOutdated } from "../../lib/version";
import "./me.css";

/** v2.81 按 docs/home-redesign.md B 做减法（= App me_screen.dart）：两组行，每行只有 图标 + 标题 + 箭头（ListRow，v2.97 起不再有私有 MeRows）。 */
type MeRow = { to: string; icon: ComponentType; title: string; value?: string };
const rows = (list: MeRow[]) => list.map(({ to, icon: Icon, title, value }) => <ListRow key={to} to={to} icon={<Icon />} title={title} value={value} />);
const GROUP1: MeRow[] = [
  { to: "/me/profile", icon: IconUser, title: "个人资料" },
  { to: "/me/tasks", icon: IconClock, title: "定时任务" },
  { to: "/me/connectors", icon: IconPlug, title: "连接的账号" },
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

/** 页头：头像 + 名字大字 + 域名小字（= App _Identity）。名字 = 称呼，没设用登录名（GET /api/profile）；没取到（加载中 / 老服务器）写“我的”，取到后淡入。
 *  v2.92 §P：整块点开个人资料弹层（称呼 / 助手名 / 头像）。 */
function Identity() {
  const p = useProfile();
  const [editing, setEditing] = useState(false);
  const name = p ? profileName(p) : null;
  const raw = server.get() || location.origin;
  let host = raw;
  try { host = new URL(raw).host || raw; } catch { /* 不是完整 URL 就原样显示 */ }
  return (
    <>
      <button className="me-who" disabled={!p} onClick={() => setEditing(true)}>
        {p && <Avatar />}
        <div className="me-id" aria-label={name ? `已登录 ${name}，服务器 ${host}` : `服务器 ${host}`}>
          <h1 key={name ?? ""} className={name ? "fade-in" : undefined}>{name ?? "我的"}</h1>
          <div className="me-server">{host}</div>
        </div>
      </button>
      {editing && <ProfileSheet onClose={() => setEditing(false)} />}
    </>
  );
}

/** 结果行行首图标：所在分区的图标（= “我的”两组行用的那几个；App 在 me_index.dart 的 MeSection.icon）。 */
const SECTION_ICON: Record<MeSection, ComponentType> = {
  me: IconUser, profile: IconUser, tasks: IconClock, connectors: IconPlug, wallet: IconCard, computer: IconComputer,
  usage: IconGauge, security: IconShield, preferences: IconSettings, feedback: IconFeedback, about: IconDoc,
};

/** 底部设置搜索胶囊（v3.0，= App me_screen.dart _SearchBar）：和输入胶囊同一位置、同一玻璃，单行所以全圆角。Esc 清空，回车打开第一条。 */
function MeSearch({ q, setQ, onFirst }: { q: string; setQ: (v: string) => void; onFirst: () => void }) {
  return (
    <div className="me-search">
      <SearchField className="glass" value={q} onChange={setQ} placeholder="搜索设置" onEnter={onFirst} />
    </div>
  );
}

/** 搜索结果（= App _MeResults）：一组行，行首 = 分区图标，标题里命中的词标亮，副标题 = 在哪。没命中：一句说明，不回显输入。 */
function MeResults({ q, hits }: { q: string; hits: MeEntry[] }) {
  if (!hits.length) return <div className="fade-in"><Hint icon={<IconSearch />} title="没有找到相关设置" text="换个说法试试；要找聊天内容，请在历史记录里搜索。" /></div>;
  return (
    <Section title="搜索结果" action={<span className="section-count">{hits.length}</span>}>
      <ListGroup className="fade-in">
        {hits.map((x) => {
          const Icon = SECTION_ICON[x.section];
          return <ListRow key={x.id} to={meLocation(x)} icon={<Icon />} title={<Highlight text={x.title} q={q} />} sub={meWhere(x)} label={`${x.title}，在${meWhere(x)}`} />;
        })}
      </ListGroup>
    </Section>
  );
}

/** “我的”（v2.81 一屏；v3.5.1 第四个标签，= App me_screen.dart）：页头（名字/域名）→ 用量卡 → 两组行 → 退出登录整行条（v3.5 照 Hark，原居中胶囊）。外观、头像颜色、回复语言都在“偏好设置”。
 *  外框 = 一级页同一套（.shell.has-bar：顶栏常驻、让出顶栏、同一条顶部渐隐）；导航在顶栏（头像为当前项），本页不再自带返回钮 / “回到主页”×、不自带渐隐（v3.5.1 删，不留两套）。
 *  v3.0：底部设置搜索（全站唯一，索引 meIndex.ts）——输入即筛，页头保留，下面换成结果；Page 的 footer 量胶囊实高，滚到底不挡“退出登录”。 */
export default function MeScreen() {
  const nav = useNavigate();
  // v2.61：先让服务器作废这个 token（登录设备里就没了这台），失败不拦
  const outdated = clientOutdated(useServerVersion());
  const logout = async () => { await http.post("/api/auth/logout", {}).catch(() => {}); auth.clear(); outbox.clear(); notifyUnauthorized(); };
  const [q, setQ] = useState("");
  const searching = q.trim() !== "";
  const hits = searchMe(q);
  return (
    <Page className="me" footer={<MeSearch q={q} setQ={setQ} onFirst={() => { if (hits[0]) nav(meLocation(hits[0])); }} />}>
      <div className="me-head enter">
        <Identity />
      </div>
      {searching ? <MeResults q={q} hits={hits} /> : (
        <div className="fade-in">
          <UsageSummary />
          <ListGroup className="me-group" enter={2}>{rows(GROUP1)}</ListGroup>
          <ListGroup className="me-group" enter={3}>{rows(GROUP2.map((r) => (r.to === "/me/about" && outdated ? { ...r, value: "请更新" } : r)))}</ListGroup>
          {/* v3.5 照 Hark：整行浅底圆角条、左侧图标 + 文字、无箭头，不进卡片组（= App me_screen.dart _LogoutBar） */}
          <div className="me-logout enter" style={stagger(4)}>
            <button className="me-logout-bar" onClick={() => void logout()}>
              <span className="row-icon" aria-hidden><IconLogout /></span>
              <span className="row-title">退出登录</span>
            </button>
          </div>
        </div>
      )}
    </Page>
  );
}
