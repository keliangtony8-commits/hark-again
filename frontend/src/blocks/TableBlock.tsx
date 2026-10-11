import type { TableBlock as T } from "../lib/types";

const isUrl = (s: string) => /^https?:\/\//.test(s);

export default function TableBlock({ block }: { block: T }) {
  return (
    <div className="card">
      {block.title && <div className="card-head">{block.title}</div>}
      <div className="blk-table-scroll">
        <table className="blk-table">
          <thead>
            <tr>{block.columns.map((c) => <th key={c}>{c}</th>)}</tr>
          </thead>
          <tbody>
            {block.rows.map((row, i) => (
              <tr key={i}>
                {row.map((cell, j) => (
                  <td key={j}>{isUrl(cell) ? <a href={cell} target="_blank" rel="noreferrer">打开</a> : cell}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {block.note && <div className="card-note">{block.note}</div>}
    </div>
  );
}
