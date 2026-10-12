/** 输入框里的 `/命令`（学 Codex / Gemini CLI 斜杠命令）。纯规则，和 app/lib/models/slash.dart 一致。
 *  目前一条 `/init`：让助手看一遍工作区写 AGENTS.md（服务器 app/init_command.py 唯一规则：存库的仍是 “/init”，
 *  给模型时换成提示词；根目录已有非空 AGENTS.md 就不调模型、直接回一句）。只在整条消息开头打 `/` 时弹候选。 */
export interface SlashCommand { name: string; title: string; hint: string }

export const INIT_COMMAND: SlashCommand = { name: "init", title: "生成 AGENTS.md", hint: "先看一遍工作区，写一份项目说明和规矩，以后每轮都照着做" };
export const SLASH_COMMANDS: SlashCommand[] = [INIT_COMMAND];
export const slashToken = (c: SlashCommand) => `/${c.name}`;

/** 光标前正在打的 `/xxx`：整段（到光标）只有 / 加字母、后面没别的字 → xxx（小写）；否则 null。 */
export function slashQueryAt(text: string, caret: number): string | null {
  if (caret < 1 || caret > text.length || text.length !== text.trimStart().length) return null;
  const head = text.slice(0, caret);
  if (!head.startsWith("/") || text.slice(caret).trim()) return null;
  const q = head.slice(1);
  return /^[A-Za-z]*$/.test(q) ? q.toLowerCase() : null;
}

export const rankSlash = (query: string) => SLASH_COMMANDS.filter((c) => c.name.startsWith(query));

/** 点了候选：整段换成 `/init `，光标放最后。 */
export const applySlash = (c: SlashCommand): [string, number] => [`${slashToken(c)} `, slashToken(c).length + 1];

/** 整条是不是 `/init`（可带补充要求；大小写不敏感；`/initial` 不算）→ 补充要求（可能是 ""）；不是 → null。 */
export function initNoteOf(text: string): string | null {
  const t = text.trim(), tok = slashToken(INIT_COMMAND), n = tok.length;
  if (t.length < n || t.slice(0, n).toLowerCase() !== tok) return null;
  if (t.length > n && t[n].trim()) return null;
  return t.slice(n).trim();
}

export const initBarText = (note: string) =>
  note ? `${INIT_COMMAND.title} · 补充：${note}` : `${INIT_COMMAND.title} · ${INIT_COMMAND.hint}`;
