import type { StatsBlock as T } from "../lib/types";
import { ValueTile } from "../ui/glass";

// 关键数字：每项一块 标签 + 大数字（+ 一句变化）= ui/glass ValueTile。和 App blocks/basic_blocks.dart StatsView 同一版式。
export default function StatsBlock({ block }: { block: T }) {
  return (
    <div className="blk-stats">
      {block.items.map((it, i) => <ValueTile key={i} label={it.label} value={it.value} note={it.note} />)}
    </div>
  );
}
