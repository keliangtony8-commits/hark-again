/** 输入框里的 `/命令`（学 Codex tui/slash_command.rs + Gemini CLI 斜杠命令）。纯规则，和 app/lib/models/slash.dart 一致。
 *  服务器命令 /init：原文照发（app/init_command.py 唯一规则）。本机命令 /new /compact /plan /model /diff /copy /status：不发消息，
 *  由 features/chat/slashActions.ts 调已有接口 / 界面。Codex 三性质：duringTask（生成中能否用）、args（能否接话；
 *  不接话的命令后面带了字 → 当普通文字发）、点候选时不接话的本机命令直接执行。只在整条消息开头打 `/` 时弹候选。 */
import { copyText } from "./copy";
import type { Message } from "./types";

export type SlashIcon = "doc" | "plus" | "brain" | "map" | "copy" | "gauge" | "swap" | "edit";
export interface SlashCommand { name: string; title: string; hint: string; icon: SlashIcon; local?: boolean; duringTask?: boolean; args?: boolean }
export interface SlashCall { command: SlashCommand; args: string }

export const INIT_COMMAND: SlashCommand = { name: "init", title: "生成 AGENTS.md", hint: "先看一遍工作区，写一份项目说明和规矩，以后每轮都照着做", icon: "doc", args: true };
export const NEW_COMMAND: SlashCommand = { name: "new", title: "新对话", hint: "另起一段对话，这段留在历史里", icon: "plus", local: true, duringTask: false };
export const COMPACT_COMMAND: SlashCommand = { name: "compact", title: "整理上文", hint: "把较早的消息压成摘要，之后每轮更省 token", icon: "brain", local: true, duringTask: false };
export const PLAN_COMMAND: SlashCommand = { name: "plan", title: "计划模式", hint: "开 / 关：只看不改，先出方案你批准；后面接话 = 打开并发出去", icon: "map", local: true, duringTask: false, args: true };
export const COPY_COMMAND: SlashCommand = { name: "copy", title: "复制上一条回答", hint: "把助手最近一条回答复制到剪贴板", icon: "copy", local: true };
export const STATUS_COMMAND: SlashCommand = { name: "status", title: "本对话用量", hint: "看用了多少 token、上文记忆和这段对话的文件", icon: "gauge", local: true };
/** v1.89：/model（Codex：生成中不能用；接名字直接换）、/diff（跳到最近一张改动卡）。 */
export const MODEL_COMMAND: SlashCommand = { name: "model", title: "换模型", hint: "不接话 = 看可选的模型；接名字（如 /model 深度）= 直接换，下一轮起用", icon: "swap", local: true, duringTask: false, args: true };
export const DIFF_COMMAND: SlashCommand = { name: "diff", title: "最近改动", hint: "跳到最近一张改动卡：看 diff、整轮撤销", icon: "edit", local: true };
export const SLASH_COMMANDS: SlashCommand[] = [INIT_COMMAND, NEW_COMMAND, COMPACT_COMMAND, PLAN_COMMAND, MODEL_COMMAND, DIFF_COMMAND, COPY_COMMAND, STATUS_COMMAND];
export const slashToken = (c: SlashCommand) => `/${c.name}`;
const duringTask = (c: SlashCommand) => c.duringTask !== false;

/** 光标前正在打的 `/xxx`：整段（到光标）只有 / 加字母、后面没别的字 → xxx（小写）；否则 null。 */
export function slashQueryAt(text: string, caret: number): string | null {
  if (caret < 1 || caret > text.length || text.length !== text.trimStart().length) return null;
  const head = text.slice(0, caret);
  if (!head.startsWith("/") || text.slice(caret).trim()) return null;
  const q = head.slice(1);
  return /^[A-Za-z]*$/.test(q) ? q.toLowerCase() : null;
}

/** 候选：名字开头对得上的。local=false（输入框不接本机命令）→ 只列服务器命令。 */
export const rankSlash = (query: string, local = true) => SLASH_COMMANDS.filter((c) => c.name.startsWith(query) && (local || !c.local));

/** 点了候选：整段换成 `/init `，光标放最后。 */
export const applySlash = (c: SlashCommand): [string, number] => [`${slashToken(c)} `, slashToken(c).length + 1];

/** 整条是不是一条命令（大小写不敏感；名字后面必须是空白或结尾；不接话的命令后面带了字 → 不算）。 */
export function slashOf(text: string, local = true): SlashCall | null {
  const m = /^\/([A-Za-z]+)(?:\s+([\s\S]*))?$/.exec(text.trim());
  if (!m) return null;
  const name = m[1].toLowerCase(), args = (m[2] ?? "").trim();
  const c = SLASH_COMMANDS.find((x) => x.name === name && (local || !x.local));
  if (!c) return null;
  return args && !c.args ? null : { command: c, args };
}

/** 整条是不是 `/init`（可带补充要求）→ 补充要求（可能是 ""）；不是 → null。和服务器 init_command.parse 一致。 */
export function initNoteOf(text: string): string | null {
  const c = slashOf(text, false);
  return c?.command === INIT_COMMAND ? c.args : null;
}

export const initBarText = (note: string) =>
  note ? `${INIT_COMMAND.title} · 补充：${note}` : `${INIT_COMMAND.title} · ${INIT_COMMAND.hint}`;

/** 现在不能用（生成中且这条命令只能空闲时用）。 */
export const slashBlocked = (c: SlashCall, busy: boolean) => busy && !duringTask(c.command);

/** 输入框上方的提示条文案。 */
export function slashBarText(c: SlashCall, busy = false): string {
  const t = c.command.title;
  if (slashBlocked(c, busy)) return `${t} · 回答结束后再用`;
  if (c.command === INIT_COMMAND) return initBarText(c.args);
  if (c.command === PLAN_COMMAND && c.args) return `${t} · 打开并发出去`;
  if (c.command === MODEL_COMMAND && c.args) return `${t} · 换成「${c.args}」`;
  return `${t} · ${c.command.hint}`;
}

/** 候选列表第二行：生成中不能用的标出来。 */
export const slashSubtitle = (c: SlashCommand, busy = false) => (busy && !duringTask(c) ? `${c.title} · 回答结束后再用` : c.title);

/** /copy 要复制的文字：最近一条有内容的助手回答（没有 → null）。 */
export function lastReplyText(messages: Message[]): string | null {
  for (let i = messages.length - 1; i >= 0; i--) {
    const m = messages[i];
    if (m.role === "user") continue;
    const t = copyText(m.blocks).trim();
    if (t) return t;
  }
  return null;
}
