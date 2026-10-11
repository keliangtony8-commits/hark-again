import type { LinksBlock as T } from "../lib/types";

const host = (u: string) => { try { return new URL(u).hostname.replace(/^www\./, ""); } catch { return u; } };

export default function LinksBlock({ block }: { block: T }) {
  return (
    <div className="blk-links">
      {block.items.map((it) => (
        <a key={it.url} className="card blk-link" href={it.url} target="_blank" rel="noreferrer">
          <span className="blk-link-fav">
            <img src={`https://icons.duckduckgo.com/ip3/${host(it.url)}.ico`} alt="" loading="lazy" />
          </span>
          <span className="blk-link-body">
            <div className="blk-link-title">{it.title ?? host(it.url)}</div>
            <div className="blk-link-host">{host(it.url)}</div>
          </span>
          {it.label && <span className="blk-link-label">{it.label}</span>}
        </a>
      ))}
    </div>
  );
}
