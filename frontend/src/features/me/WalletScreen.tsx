import { useState } from "react";
import { useResource } from "../../hooks/useResource";
import { BRAND_NAMES, cardBrand, cardDigits, cardLine, cardNumberError, cvcError, expiryError, formatExpiry, groupCardNumber,
  maskedNumber, parseExpiry, walletSummary, type PaymentCard } from "../../lib/wallet";
import { IconCard, IconEdit, IconMore, IconPlus, IconTrash } from "../../ui/icons";
import { ListGroup, ListRow, Menu, Page, PageHeader, PageIntro, Section, Sheet, Skeleton, StarterCard } from "../../ui/kit";
import { confirmDialog } from "../../ui/dialog";

const EMPTY = { number: "", exp: "", cvc: "", holder: "", postal_code: "", label: "" };

/** 钱包（v2.74，对标 Hark 设置里的 Wallets）：存付款卡，结账时我在云浏览器里替你填（先在订单卡上问你一次）。
 *  版式同保险箱（页头摘要 → 起步卡 → 列表错峰进场）；加卡弹层上方一张随输入变化的卡面。规则在 lib/wallet.ts。 */
export default function WalletScreen() {
  const cards = useResource<PaymentCard>("/api/wallet");
  const [draft, setDraft] = useState<typeof EMPTY | null>(null);
  const [tried, setTried] = useState(false);
  const [rename, setRename] = useState<{ id: string; label: string } | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);

  const brand = cardBrand(draft?.number ?? "");
  const errs = draft ? { number: cardNumberError(draft.number), exp: expiryError(draft.exp), cvc: cvcError(draft.cvc, brand) } : null;
  const filled = !!draft && !!draft.number && !!draft.exp && !!draft.cvc;

  const open = () => { setDraft({ ...EMPTY }); setTried(false); setErr(null); };
  const save = async () => {
    if (!draft || !errs) return;
    setTried(true);
    if (errs.number || errs.exp || errs.cvc) return;
    const [m, y] = parseExpiry(draft.exp)!;
    setErr(null);
    try {
      const x = await cards.create({ number: cardDigits(draft.number), exp_month: m, exp_year: y, cvc: draft.cvc.trim(), holder: draft.holder.trim(),
        postal_code: draft.postal_code.trim(), label: draft.label.trim() } as never);
      await cards.reload(); // 服务器按添加先后排
      setSaved(`已加密保存「${x.label}」`);
      setDraft(null);
    } catch (e) { setErr(e instanceof Error ? e.message : "保存失败"); }
  };
  const saveName = async () => {
    if (!rename?.label.trim()) return;
    try { await cards.update(rename.id, { label: rename.label.trim() }); setRename(null); }
    catch (e) { setErr(e instanceof Error ? e.message : "保存失败"); }
  };
  const remove = async (c: PaymentCard) => {
    if (await confirmDialog({ title: `删除「${c.label}」？`, text: "之后结账我就不能替你填这张卡了。" })) void cards.remove(c.id);
  };
  const field = (key: keyof typeof EMPTY, label: string, props: React.InputHTMLAttributes<HTMLInputElement>, error?: string | null) => draft && (
    <label className="form-field"><span>{label}</span>
      <input value={draft[key]} autoComplete="off" spellCheck={false} {...props}
        onChange={(e) => {
          const v = e.target.value;
          const next = key === "number" ? groupCardNumber(cardDigits(v).slice(0, 19))
            : key === "exp" ? formatExpiry(v, v.length < draft.exp.length)
            : key === "cvc" ? cardDigits(v).slice(0, 4) : v;
          setDraft({ ...draft, [key]: next });
        }} />
      {tried && error ? <small className="form-error">{error}</small> : null}</label>
  );

  return (
    <Page header={<PageHeader title="钱包" back action={
      <button className="icon-btn" onClick={open} aria-label="添加付款卡"><IconPlus /></button>} />}>
      <PageIntro loading={cards.loading} summary={walletSummary(cards.items)}
        line="结账时我在云浏览器里替你填卡，付款前一定先在订单卡上问你。卡号加密存在你自己的服务器上，之后只显示尾号。" />
      {saved && <div className="notice ok" role="status" onClick={() => setSaved(null)}>{saved}</div>}
      {cards.loading ? <Skeleton /> : cards.items.length === 0 ? (
        <StarterCard title="钱包是空的" text="添加常用银行卡，网购和预订酒店时无需重复输入卡号。">
          <button className="btn btn-ghost" onClick={open}><IconCard size={16} />添加付款卡</button>
        </StarterCard>
      ) : (
        <Section title={`付款卡 · ${cards.items.length}`}>
          <ListGroup>
            {cards.items.map((c, i) => (
              <ListRow key={c.id} enter={i + 1} icon={<IconCard />} title={c.label} problem={c.expired ? "已过期" : undefined} sub={cardLine(c)} control={
                <Menu trigger={<IconMore />} label={`${c.label} 的操作`} items={[
                  { label: "改名", icon: <IconEdit />, onSelect: () => setRename({ id: c.id, label: c.label }) },
                  { label: "删除", icon: <IconTrash />, danger: true, onSelect: () => void remove(c) }]} />} />
            ))}
          </ListGroup>
        </Section>
      )}
      {draft && (
        <Sheet title="添加付款卡" onClose={() => setDraft(null)} actions={<>
          <button className="btn btn-ghost" onClick={() => setDraft(null)}>取消</button>
          <button className="btn btn-primary" disabled={!filled} onClick={save}>加密保存</button>
        </>}>
          <div className="wallet-face" aria-label="卡面预览">
            <div className="wallet-face-top">
              <span className="wallet-face-label">{draft.label.trim() || "新卡"}</span>
              <span key={brand} className="wallet-face-soft enter">{BRAND_NAMES[brand] ?? "银行卡"}</span>
            </div>
            <div className="wallet-face-number">{maskedNumber(draft.number, brand)}</div>
            <div className="wallet-face-bottom wallet-face-soft">
              <span>{draft.holder.trim() ? draft.holder.trim().toUpperCase() : "持卡人"}</span>
              <span>{draft.exp || "MM/YY"}</span>
            </div>
          </div>
          {field("number", "卡号", { inputMode: "numeric", placeholder: "4111 1111 1111 1111", autoFocus: true }, errs?.number)}
          <div className="wallet-pair">
            {field("exp", "有效期", { inputMode: "numeric", placeholder: "MM/YY" }, errs?.exp)}
            {field("cvc", "安全码", { inputMode: "numeric", type: "password", placeholder: brand === "amex" ? "4 位" : "背面 3 位" }, errs?.cvc)}
          </div>
          {field("holder", "持卡人（选填）", { placeholder: "卡面上的名字" })}
          {field("postal_code", "账单邮编（选填）", { inputMode: "numeric", placeholder: "有的海外网站要" })}
          {field("label", "名字（选填）", { placeholder: "比如：招行信用卡" })}
          {err && <p className="form-error" role="alert">{err}</p>}
          <small className="muted">只上传这一次，之后只显示尾号；付款前我一定先问你。</small>
        </Sheet>
      )}
      {rename && (
        <Sheet title="给这张卡起个名字" onClose={() => setRename(null)} actions={<>
          <button className="btn btn-ghost" onClick={() => setRename(null)}>取消</button>
          <button className="btn btn-primary" disabled={!rename.label.trim()} onClick={saveName}>保存</button>
        </>}>
          <label className="form-field"><span>名字</span>
            <input value={rename.label} autoFocus onChange={(e) => setRename({ ...rename, label: e.target.value })} placeholder="比如：招行信用卡" /></label>
        </Sheet>
      )}
    </Page>
  );
}
