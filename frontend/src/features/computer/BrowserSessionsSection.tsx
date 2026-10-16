import { useState } from "react";
import { useSwr } from "../../hooks/useSwr";
import { http } from "../../lib/api";
import { BROWSER_SESSIONS_EMPTY, BROWSER_SESSIONS_EMPTY_LINE, BROWSER_SESSIONS_PATH, type BrowserSession, type BrowserSessionList,
  browserSessionDetail, browserSessionExpired, browserSessionHint, browserSessionSemantics, browserSignOutText, sortBrowserSessions } from "../../lib/browserSessions";
import { confirmDialog, noticeDialog } from "../../ui/dialog";
import { IconGlobe, IconGlobeOff } from "../../ui/icons";
import { ListGroup, ListRow, Section } from "../../ui/kit";
import "./computer.css";

/** “浏览器登录”一节（v1.26，= App features/computer/browser_sessions_section.dart）：云浏览器按网站保存的会话。
 *  每行：网站名 · 上次用 · 登录已保存，行尾“正在用” + 退出（确认后关掉那个网站的浏览器并删掉登录）。
 *  登录过期（v1.36）：行尾“已过期”警示色、图标换成断开的地球，说明行“登录过期了，用到时会请你重新登录”。
 *  只在“我的电脑”页（浏览器整个账号共用）。加载中 / 服务连不上 → 整节不画。 */
export default function BrowserSessionsSection({ enter }: { enter?: number }) {
  const { data, mutate } = useSwr<BrowserSessionList>(BROWSER_SESSIONS_PATH);
  const [busy, setBusy] = useState<Set<string>>(new Set());
  if (!data) return null;
  const list = sortBrowserSessions(data.sessions);

  const signOut = async (s: BrowserSession) => {
    if (!await confirmDialog({ title: `退出 ${s.label}？`, text: browserSignOutText(s), action: "退出" })) return;
    setBusy((b) => new Set(b).add(s.name));
    try {
      await http.del(`${BROWSER_SESSIONS_PATH}/${encodeURIComponent(s.name)}`);
      mutate((v) => { const cur = v ?? data; return { ...cur, sessions: cur.sessions.filter((x) => x.name !== s.name) }; });
    } catch (e) { void noticeDialog("退出失败", e instanceof Error ? e.message : undefined); }
    setBusy((b) => { const n = new Set(b); n.delete(s.name); return n; });
  };

  return (
    <Section title="浏览器登录" enter={enter}>
      <ListGroup>
        {list.length === 0 ? (
          <ListRow icon={<IconGlobe />} title={BROWSER_SESSIONS_EMPTY} sub={BROWSER_SESSIONS_EMPTY_LINE} />
        ) : list.map((s, i) => {
          const hint = browserSessionHint(s), expired = browserSessionExpired(s);
          return (
            <ListRow key={s.name} className="browser-session" enter={i} role="group" label={browserSessionSemantics(s)}
              icon={expired ? <IconGlobeOff /> : <IconGlobe />} title={s.label} sub={browserSessionDetail(s)} control={<>
                {hint && <span className={`row-hint computer-hint${expired ? " is-warn" : ""}`} aria-hidden>{hint}</span>}
                <button className="btn btn-ghost btn-sm" disabled={busy.has(s.name)} onClick={() => void signOut(s)}>
                  {busy.has(s.name) ? "正在退出" : "退出"}</button>
              </>} />
          );
        })}
      </ListGroup>
    </Section>
  );
}
