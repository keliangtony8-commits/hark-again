// 改动卡（v1.68）的纯规则，和 App models/changes.dart 同款；后端规则在 app/turn_changes.py。
import type { ChangesBlock, FileChange } from "./types";

export const changesCount = (b: ChangesBlock) => b.files.length + (b.more ?? 0);

export const changesTitle = (b: ChangesBlock) =>
  b.undone ? `已撤销 ${changesCount(b)} 个文件的改动` : `改了 ${changesCount(b)} 个文件`;

export const changesTotals = (b: ChangesBlock): [number, number] =>
  b.files.reduce<[number, number]>(([a, r], f) => [a + f.added, r + f.removed], [0, 0]);

export const changesUndoable = (b: ChangesBlock) => !!b.token && !b.undone;

export function changesNote(b: ChangesBlock): string | null {
  const big = b.files.filter((f) => f.big).length;
  if (b.undone) return "文件已回到这一轮之前的样子";
  if (!b.token) return "文件太大，没有留撤销记录";
  if (big > 0) return `${big} 个大文件不能撤销`;
  return null;
}

export const changeTag = (f: FileChange) => (f.deleted ? "已不在" : f.big ? "大文件" : null);

export function changesSemantics(b: ChangesBlock): string {
  const [a, r] = changesTotals(b);
  return `${changesTitle(b)}，增加 ${a} 行，删除 ${r} 行：${b.files.map((f) => f.path).join("、")}`;
}
