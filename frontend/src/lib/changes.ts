// 改动卡（v1.68）的纯规则，和 App models/changes.dart 同款；后端规则在 app/turn_changes.py。
import type { ChangesBlock, FileChange, Message } from "./types";

export const changesCount = (b: ChangesBlock) => b.files.length + (b.more ?? 0);

/** 改动是谁的：一轮回复（消息里的改动卡）还是一个后台任务（v2.18 任务卡里嵌的那份）。只影响措辞。 */
export type ChangesScope = "turn" | "job";

/** 任务卡要不要画改动区：结束了且列出了文件。 */
export const jobChangesShown = (b: ChangesBlock | null | undefined): b is ChangesBlock => !!b && Array.isArray(b.files) && b.files.length > 0;

export const changesTitle = (b: ChangesBlock, scope: ChangesScope = "turn") =>
  b.undone ? `已撤销 ${changesCount(b)} 个文件的改动` : `${scope === "job" ? "任务" : ""}改了 ${changesCount(b)} 个文件`;

export const changesConfirm = (b: ChangesBlock, scope: ChangesScope = "turn") => scope === "job"
  ? { title: "撤销这个任务的文件改动？", text: `${changesCount(b)} 个文件会回到任务开始前的样子；它新建的文件会被删掉。` }
  : { title: "撤销这一轮的文件改动？", text: `${changesCount(b)} 个文件会回到助手改之前的样子；这一轮新建的文件会被删掉。` };

export const changesTotals = (b: ChangesBlock): [number, number] =>
  b.files.reduce<[number, number]>(([a, r], f) => [a + f.added, r + f.removed], [0, 0]);

export const changesUndoable = (b: ChangesBlock) => !!b.token && !b.undone;

export function changesNote(b: ChangesBlock, scope: ChangesScope = "turn"): string | null {
  const big = b.files.filter((f) => f.big).length;
  const cmd = b.files.filter((f) => f.command).length; // v2.14 命令改的（后端 app/command_changes.py）
  if (b.undone) return scope === "job" ? "文件已回到任务开始前的样子" : "文件已回到这一轮之前的样子";
  const parts = [
    !b.token ? "文件太大，没有留撤销记录" : big > 0 ? `${big} 个大文件不能撤销` : "",
    cmd > 0 ? `其中 ${cmd} 个是命令改的` : "",
    b.overlap ? "同时还有别的后台任务，可能也算进来了" : "",          // v2.18 任务那份
    b.shared ? `另有 ${b.shared} 个文件这期间对话里也改过，算在那一轮` : "",
  ].filter(Boolean);
  return parts.length ? parts.join(" · ") : null;
}

/** 行右侧代替 “+N −M” 的字：已不在 / 大文件 / v2.16 只改了权限（+0 −0）时那句权限的话。 */
export const changeTag = (f: FileChange) =>
  f.deleted ? "已不在" : f.big ? "大文件" : f.mode && !f.added && !f.removed ? f.mode : null;

export function changesSemantics(b: ChangesBlock, scope: ChangesScope = "turn"): string {
  const [a, r] = changesTotals(b);
  return `${changesTitle(b, scope)}，增加 ${a} 行，删除 ${r} 行：${b.files.map((f) => f.path).join("、")}`;
}

/** `/diff`（v1.89，同 App latestChanges）：最近一条带改动卡的消息 → [消息 id, 那张卡]；没有 → null。 */
export function latestChanges(messages: Message[]): [string, ChangesBlock] | null {
  for (let i = messages.length - 1; i >= 0; i--) {
    const bs = messages[i].blocks;
    for (let j = bs.length - 1; j >= 0; j--) {
      const b = bs[j];
      if (b.type === "changes" && b.files.length > 0) return [messages[i].id, b];
    }
  }
  return null;
}
export function latestChangesNote(b: ChangesBlock): string {
  if (b.undone) return changesTitle(b);
  const [a, r] = changesTotals(b);
  return `${changesTitle(b)} · +${a} −${r}`;
}
export const NO_CHANGES = "这段对话里助手还没改过文件";
