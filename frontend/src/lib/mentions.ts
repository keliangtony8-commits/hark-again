/** 输入框里的 `@文件`（与 App features/chat/mentions.dart 同规则）：打 @ 列出工作区文件，边打边筛，选中补成 `@路径 `。
 *  只补文字；发出后由服务器 app/file_mentions.py（移植自 Gemini CLI @ 命令）解析成引用附到消息上。
 *  @ 前面不能是英文字母/数字/下划线/点/反斜杠/@（邮箱不弹），中文紧挨着可以；遇到空白和标点结束。
 *  排序（学 Codex file-search 的思路）：文件名开头 > 文件名包含 > 路径包含 > 按顺序出现；同分新的在前、路径短的在前。 */
import type { ProjectFile } from "./types";

export const MENTION_MAX = 5;
export type MentionQuery = { start: number; end: number; query: string };

const STOP = /[\s,;!?()[\]{}"'`，。；：！？、（）【】《》“”‘’「」]/;
const BLOCKED_BEFORE = /[A-Za-z0-9_.\\@]/;

export function mentionAt(text: string, caret: number): MentionQuery | null {
  if (caret < 0 || caret > text.length) return null;
  for (let i = caret - 1; i >= 0; i--) {
    const ch = text[i];
    if (ch === "@") {
      if (i > 0 && BLOCKED_BEFORE.test(text[i - 1])) return null;
      return { start: i, end: caret, query: text.slice(i + 1, caret) };
    }
    if (STOP.test(ch)) return null;
  }
  return null;
}

function score(f: ProjectFile, q: string): number | null {
  if (!q) return 0;
  const name = f.name.toLowerCase(), path = f.path.toLowerCase();
  if (name.startsWith(q)) return 400;
  if (name.includes(q)) return 300;
  if (path.includes(q)) return 200;
  let at = 0;
  for (const c of q) {
    at = path.indexOf(c, at);
    if (at < 0) return null;
    at++;
  }
  return 100;
}

export function rankMentions(files: ProjectFile[], query: string, max = MENTION_MAX): ProjectFile[] {
  const q = query.toLowerCase().trim();
  return files
    .flatMap((f) => { const s = score(f, q); return s === null ? [] : [{ f, s }]; })
    .sort((a, b) => b.s - a.s || (b.f.modified ?? 0) - (a.f.modified ?? 0) || a.f.path.length - b.f.path.length
      || (a.f.path < b.f.path ? -1 : a.f.path > b.f.path ? 1 : 0))
    .slice(0, max)
    .map((x) => x.f);
}

/** 带空白或标点的路径用双引号包（服务器认 `@"a b.txt"`）。 */
export const mentionToken = (path: string) => (STOP.test(path) && !path.includes('"') ? `@"${path}"` : `@${path}`);

/** 换掉正在打的 @xxx → [新文字, 光标位置]。 */
export function applyMention(text: string, m: MentionQuery, path: string): [string, number] {
  const rest = text.slice(m.end);
  const spaced = rest.startsWith(" ");
  const insert = mentionToken(path) + (spaced ? "" : " ");
  return [text.slice(0, m.start) + insert + rest, m.start + insert.length + (spaced ? 1 : 0)];
}
