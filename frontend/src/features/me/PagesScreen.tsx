import { useState } from "react";
import { useResource } from "../../hooks/useResource";
import { copyLink, isLive, shareLink } from "../../lib/pages";
import type { SitePage } from "../../lib/types";
import { IconCopy, IconExternal, IconLayout, IconMore } from "../../ui/icons";
import { Hint, Menu, Page, PageHeader, Sheet, Skeleton } from "../../ui/kit";
import { confirmDialog } from "../../ui/dialog";

/** 我做过的网页：打开、复制 / 分享链接、重命名、下线 / 重新发布、删除。
 * 下线 ≠ 删除：文件留着、公开链接暂时 404，重新发布后同一个链接恢复。状态只走 PATCH /api/pages/{slug}。 */
export default function PagesScreen() {
  const pages = useResource<SitePage>("/api/pages");
  const [copied, setCopied] = useState<string | null>(null);
  const [renaming, setRenaming] = useState<{ id: string; title: string } | null>(null);
  const [error, setError] = useState<string | null>(null);

  const patch = async (id: string, body: Partial<SitePage>) => {
    setError(null);
    try { await pages.update(id, body); return true; } catch (e) { setError(e instanceof Error ? e.message : "操作失败"); return false; }
  };
  const copy = async (p: SitePage) => { if (await copyLink(p.url)) setCopied(p.slug); };

  return (
    <Page header={<PageHeader title="Pages" back />}>
      <p className="desc">行程、邀请函、菜单这类要给别人看的东西，我会做成网页。链接带随机后缀，不会被搜到；不想让人看时可以先下线，链接不变。</p>
      {error && <p className="desc" role="alert">{error}</p>}
      {pages.loading ? <Skeleton /> : pages.items.length === 0 ? (
        <Hint icon={<IconLayout size={26} />} title="还没有 Page" text="在聊天里说“把这个行程做成网页”试试。" />
      ) : (
        <div className="list">
          {pages.items.map((p) => {
            const live = isLive(p);
            return (
              <div key={p.id} className={`row ${live ? "" : "row-off"}`}>
                <span className="row-icon"><IconLayout /></span>
                <div className="row-body"><div className="row-title">{p.title}</div>
                  <div className="row-sub">{new Date(p.updated * 1000).toLocaleDateString("zh-CN")} · /p/{p.slug}</div></div>
                {live ? (<>
                  <button className="icon-btn" aria-label="复制链接" onClick={() => copy(p)}>{copied === p.slug ? "✓" : <IconCopy />}</button>
                  <a className="icon-btn" href={p.url} target="_blank" rel="noreferrer" aria-label="打开"><IconExternal /></a>
                </>) : (
                  <span className="chip">已下线</span>
                )}
                <Menu trigger={<IconMore />} label={`「${p.title}」的更多操作`} items={[
                  ...(live && "share" in navigator ? [{ label: "分享链接", onSelect: () => { void shareLink(p.url, p.title); } }] : []),
                  { label: "重命名", onSelect: () => setRenaming({ id: p.id, title: p.title }) },
                  live
                    ? { label: "下线", onSelect: async () => { if (await confirmDialog({ title: `下线「${p.title}」？`, text: "链接会暂时打不开，页面还留着，随时可重新发布，链接不变。", action: "下线", danger: false })) void patch(p.id, { published: false }); } }
                    : { label: "重新发布", onSelect: () => { void patch(p.id, { published: true }); } },
                  { label: "删除", danger: true, onSelect: async () => { if (await confirmDialog({ title: `删除「${p.title}」？`, text: "链接会失效。只想暂时不让人看，可以用“下线”。" })) void pages.remove(p.id); } },
                ]} />
              </div>
            );
          })}
        </div>
      )}
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
