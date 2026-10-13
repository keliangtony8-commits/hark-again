import type { OriginBlock, RelayBlock } from "./types";

/** v2.23 跨项目转交的文案（和 App models/block.dart OriginBlock / RelayBlock 同一套）。规则在后端 app/project_relay.py。 */
export const originLabel = (b: OriginBlock) => `来自 ${b.emoji ?? "💬"} ${b.name}`;
export const originSemantics = (b: OriginBlock) => (b.conversation_id ? `${b.name} 转交来的消息，点按打开原对话` : `${b.name} 转交来的消息`);

export function relayMeta(b: RelayBlock): string {
  const files = b.files ?? [];
  return [
    b.new_conversation ? "新开了一段对话" : "接在最近的对话里",
    ...(files.length === 1 ? [`带了 ${files[0]}`] : files.length > 1 ? [`带了 ${files[0]} 等 ${files.length} 个文件`] : []),
  ].join(" · ");
}
export const relaySemantics = (b: RelayBlock) => `已交给项目 ${b.name}：${b.text ?? ""}。${relayMeta(b)}。点按打开`;
