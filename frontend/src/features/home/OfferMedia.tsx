import { useState } from "react";
import type { HomeCard } from "../../lib/types";
import { IconArrowUpRight, IconImageOff } from "../../ui/icons";

/** 建议卡的配图 / 原页（v0.91，和 App action_card.dart OfferImage/OfferSource 同义）：只认 http(s)，域名去掉 www.。 */
export const webUrl = (v?: string | null) => (v && /^https?:\/\//i.test(v) ? v : null);

export function linkHost(c: HomeCard): string | null {
  const u = webUrl(c.link_url);
  if (!u) return null;
  try {
    const h = new URL(u).host;
    return h.replace(/^www\./, "") || null;
  } catch {
    return null;
  }
}

/** 卡顶宽图（2:1），加载完淡入，打不开显示占位；有原页时整张图是去原页的链接。 */
export function OfferImage({ card }: { card: HomeCard }) {
  const [state, setState] = useState<"loading" | "ok" | "bad">("loading");
  const url = webUrl(card.image_url);
  if (!url) return null;
  const img = state === "bad"
    ? <span className="offer-img-bad"><IconImageOff /></span>
    : <img src={url} alt={card.title} loading="lazy" referrerPolicy="no-referrer" className={state === "ok" ? "ok" : ""}
        onLoad={() => setState("ok")} onError={() => setState("bad")} />;
  const link = webUrl(card.link_url);
  return link
    ? <a className="offer-img" href={link} target="_blank" rel="noreferrer" aria-label={`打开原页 ${linkHost(card)}`}>{img}</a>
    : <div className="offer-img">{img}</div>;
}

/** 正文下“来源 · 域名 ↗”。 */
export function OfferSource({ card }: { card: HomeCard }) {
  const host = linkHost(card);
  if (!host) return null;
  return (
    <a className="offer-source" href={card.link_url!} target="_blank" rel="noreferrer">
      <span>来源 · {host}</span><IconArrowUpRight size={14} />
    </a>
  );
}
