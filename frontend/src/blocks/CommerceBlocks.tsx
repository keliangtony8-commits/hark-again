import { useState } from "react";
import type { OrderBlock as O, ProductsBlock as P } from "../lib/types";
import CopyButton from "../ui/CopyButton";
import { monogramOf } from "../lib/monogram";
import { IconArrowUpRight, IconCard, IconImageOff, IconPlace, IconReceipt, IconSpark } from "../ui/icons";
import { useBlockActions } from "./actions";

// 购物类的卡（= App blocks/commerce_blocks.dart）：商品宫格（挑东西）、订单卡（付款前确认 / 下单后回执）。

const http = (u?: string | null) => (u && /^https?:\/\//i.test(u) ? u : null);

/** 网络图：先铺占位底色，下好了淡入，坏图留一个安静的图标。宫格和订单行共用。 */
function NetImg({ url }: { url: string }) {
  const [state, setState] = useState<"loading" | "ok" | "bad">("loading");
  return state === "bad"
    ? <span className="blk-img-bad"><IconImageOff /></span>
    : <img src={url} alt="" loading="lazy" referrerPolicy="no-referrer" className={state === "ok" ? "ok" : ""}
        onLoad={() => setState("ok")} onError={() => setState("bad")} />;
}

/** 没图时的占位：tile 底 + 名字首字（衬线）。宫格大格与清单小格共用。 */
const Monogram = ({ name }: { name: string }) => <span className="blk-monogram" aria-hidden="true">{monogramOf(name)}</span>;

/** 商品宫格：自适应列（每格 ≥148px，最多 4 列），一格 = 方图 + 名字 + 价格 + 一行补充；底部一句推荐。
 *  缺图的格子用字标占位；一件都没有图时改排清单（字标 + 名字/补充 + 右侧价格），不铺整屏空白方块。 */
export function ProductsBlock({ block }: { block: P }) {
  const items = block.items.filter((i) => i.name);
  if (!items.length) return null;
  const grid = items.some((i) => http(i.image));
  return (
    <section className="card blk-products">
      {block.title && <h3 className="blk-products-title">{block.title}</h3>}
      <div className={grid ? "blk-products-grid" + (items.length === 1 ? " single" : "") : "blk-products-list"}>
        {items.map((it, i) => {
          const url = http(it.url), img = http(it.image);
          const inner = grid ? (
            <>
              <span className="blk-product-pic">{img ? <NetImg url={img} /> : <Monogram name={it.name} />}</span>
              <span className="blk-product-name">{it.name}</span>
              {it.price && <span className="blk-product-price">{it.price}</span>}
              {it.meta && <span className="blk-product-meta">{it.meta}</span>}
            </>
          ) : (
            <>
              <span className="blk-product-thumb"><Monogram name={it.name} /></span>
              <span className="blk-product-text">
                <span className="blk-product-name">{it.name}</span>
                {it.meta && <span className="blk-product-meta">{it.meta}</span>}
              </span>
              {it.price && <span className="blk-product-price">{it.price}</span>}
              {url && <span className="blk-product-go"><IconArrowUpRight size={16} /></span>}
            </>
          );
          const cls = (grid ? "blk-product" : "blk-product-row") + " enter";
          return url
            ? <a key={i} className={cls} style={{ ["--i" as string]: i }} href={url} target="_blank" rel="noopener noreferrer"
                aria-label={[it.name, it.price, it.meta, "打开商品页"].filter(Boolean).join("，")}>{inner}</a>
            : <div key={i} className={cls} style={{ ["--i" as string]: i }}>{inner}</div>;
        })}
      </div>
      {block.pick && <p className="blk-products-pick"><IconSpark size={16} />{block.pick}</p>}
    </section>
  );
}

const STATE_TEXT: Record<O["state"], string> = { pending: "等你确认", approved: "已确认", rejected: "没有下单", expired: "已过期", placed: "已下单" };

/** 订单卡：一张小票。等确认时边框换提醒色，底部 不买了 / 确认下单（走审批）；回执显示订单号可复制。 */
export function OrderBlock({ block }: { block: O }) {
  const { replyApproval } = useBlockActions();
  const [sent, setSent] = useState(false);
  const pending = block.state === "pending";
  const ended = block.state === "rejected" || block.state === "expired";
  const reply = (ok: boolean) => { setSent(true); replyApproval?.(block.id, ok); };
  const fees = block.breakdown ?? [];
  return (
    <section className={`card blk-order ${block.state}`} aria-label={`订单：${block.merchant}，合计 ${block.total}，${STATE_TEXT[block.state]}`}>
      <header className="blk-order-head">
        <IconReceipt size={18} />
        <span className="blk-order-merchant">{block.merchant}</span>
        <span key={block.state} className="blk-order-state icon-pop">{STATE_TEXT[block.state]}</span>
      </header>
      <div className={"blk-order-body" + (ended ? " ended" : "")}>
        {block.items.map((it, i) => (
          <div key={i} className="blk-order-line">
            {http(it.image) && <span className="blk-order-thumb"><NetImg url={http(it.image)!} /></span>}
            <span className="blk-order-name">{it.name}{it.note && <small>{it.note}</small>}</span>
            {(it.qty ?? 1) > 1 && <span className="blk-order-qty">×{it.qty}</span>}
            <span>{it.price}</span>
          </div>
        ))}
        {(fees.length > 0 || block.items.length > 1) && <hr />}
        {fees.map((f, i) => <div key={i} className="blk-order-fee"><span>{f.label}</span><span>{f.amount}</span></div>)}
        <div className="blk-order-total"><span>合计</span><b>{block.total}</b></div>
        {block.destination && <div className="blk-order-meta"><IconPlace size={16} />{block.destination}</div>}
        {block.payment && <div className="blk-order-meta"><IconCard size={16} />{block.payment}</div>}
        {block.state === "placed" && block.order_number && (
          <div className="blk-order-meta number">订单号 {block.order_number}<CopyButton text={block.order_number} label="复制订单号" /></div>
        )}
      </div>
      {pending && replyApproval && (
        <div className="blk-order-actions">
          <button className="btn btn-ghost" disabled={sent} onClick={() => reply(false)}>不买了</button>
          <button className="btn btn-primary" disabled={sent} onClick={() => reply(true)}>{block.action || "确认下单"}</button>
        </div>
      )}
    </section>
  );
}
