import { useState } from "react";
import { useResource } from "../../hooks/useResource";
import { copyLink, isLive, shareLink } from "../../lib/pages";
import type { SitePage } from "../../lib/types";
import { IconCheck, IconCopy, IconExternal, IconLayout, IconMore, IconSpark } from "../../ui/icons";
import { ListGroup, ListRow, Menu, Page, PageHeader, PageIntro, Section, Sheet, Skeleton, StarterCard, stagger } from "../../ui/kit";
import { useAskInNewChat } from "../../shell/LaunchComposer";
import { formatWhen } from "../../lib/format";
import { PAGE_STARTERS, groupPages, pagesSummary } from "./pageLibrary";
import { confirmDialog } from "../../ui/dialog";

/** 我做过的网页（版式同保险箱/技能页：页头摘要 → 空时起步卡 → 在线 / 已下线分组带数量 → 错峰进场）：打开、复制 / 分享链接、重命名、下线 / 重新发布、删除。
 * 下线 ≠ 删除：文件留着、公开链接暂时 404，重新发布后同一个链接恢复。状态只走 PATCH /api/pages/{slug}。 */
export default function PagesScreen() {
  const pages = useResource<SitePage>("/api/pages");
  const [copied, setCopied] = useState<string | null>(null);
  const [renaming, setRenaming] = useState<{ id: string; title: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const ask = useAskInNewChat();

  const patch = async (id: string, body: Partial<SitePage>) => {
    setError(null);
    try { await pages.update(id, body); return true; } catch (e) { setError(e instanceof Error ? e.message : "操作失败"); return false; }
  };
  const copy = async (p: SitePage) => { if (await copyLink(p.url)) setCopied(p.slug); };

  const g = groupPages(pages.items);
  let n = 0; // 整页错峰序号
  const rows = (items: SitePage[]) => (
    <ListGroup>
      {items.map((p) => {
        const live = isLive(p);
        return (
          <ListRow key={p.id} off={!live} enter={++n} icon={<IconLayout />} title={p.title}
            sub={`${formatWhen(new Date(p.updated * 1000).toISOString())} · /p/${p.slug}`} control={<>
            {live ? (<>
              <button className="icon-btn" aria-label="复制链接" onClick={() => copy(p)}>
                <span key={copied === p.slug ? "ok" : "copy"} className="icon-pop">{copied === p.slug ? <IconCheck /> : <IconCopy />}</span></button>
              <a className="icon-btn" href={p.url} target="_blank" rel="noreferrer" aria-label="打开"><IconExternal /></a>
            </>) : (
              <span className="row-hint">已下线</span>
            )}
            <Menu trigger={<IconMore />} label={`「${p.title}」的更多操作`} items={[
              ...(live && "share" in navigator ? [{ label: "分享链接", onSelect: () => { void shareLink(p.url, p.title); } }] : []),
              { label: "重命名", onSelect: () => setRenaming({ id: p.id, title: p.title }) },
              live
                ? { label: "下线", onSelect: async () => { if (await confirmDialog({ title: `下线「${p.title}」？`, text: "链接会暂时打不开，页面还留着，随时可重新发布，链接不变。", action: "下线", danger: false })) void patch(p.id, { published: false }); } }
                : { label: "重新发布", onSelect: () => { void patch(p.id, { published: true }); } },
              { label: "删除", danger: true, onSelect: async () => { if (await confirmDialog({ title: `删除「${p.title}」？`, text: "链接会失效。只想暂时不让人看，可以用“下线”。" })) void pages.remove(p.id); } },
            ]} />
          </>} />
        );
      })}
    </ListGroup>
  );

  return (
    <Page header={<PageHeader title="Pages" back />}>
      <PageIntro loading={pages.loading} summary={pagesSummary(pages.items)}
        line="行程、邀请函、菜单等需要分享的内容，我会制作成网页。链接含随机后缀，不会被搜索到；可随时下线，链接保持不变。" />
      {error && <p className="desc" role="alert">{error}</p>}
      {pages.loading ? <Skeleton /> : (<>
        {pages.items.length === 0 && (
          <StarterCard title="做第一个网页" text="在聊天里说一句“把这个做成网页”就行，做好的页面都会出现在这里。">
            {PAGE_STARTERS.map((s) => (
              <button key={s.label} className="btn btn-ghost" onClick={() => ask(s.prompt)}><IconSpark size={16} />{s.label}</button>
            ))}
          </StarterCard>
        )}
        {g.live.length > 0 && <Section title={`在线 · ${g.live.length}`}>{rows(g.live)}</Section>}
        {g.off.length > 0 && <Section title={`已下线 · ${g.off.length}`}>{rows(g.off)}</Section>}
      </>)}
      {renaming && (
        <Sheet title="重命名" onClose={() => setRenaming(null)} actions={<>
          <button className="btn btn-ghost" onClick={() => setRenaming(null)}>取消</button>
          <button className="btn btn-primary" disabled={!renaming.title.trim()}
            onClick={async () => { if (await patch(renaming.id, { title: renaming.title.trim() })) setRenaming(null); }}>保存</button>
        </>}>
          <label className="form-field"><span>标题</span>
            <input value={renaming.title} autoFocus onChange={(e) => setRenaming({ ...renaming, title: e.target.value })}
              onKeyDown={(e) => { if (e.key === "Enter" && renaming.title.trim()) void patch(renaming.id, { title: renaming.title.trim() }).then((ok) => ok && setRenaming(null)); }} /></label>
        </Sheet>
      )}
    </Page>
  );
}
