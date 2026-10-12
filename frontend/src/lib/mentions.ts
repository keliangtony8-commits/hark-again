/** 输入框里的 `@文件`（与 App features/chat/mentions.dart 同规则）：打 @ 列出工作区文件，边打边筛，选中补成 `@路径 `。
 *  只补文字；发出后由服务器 app/file_mentions.py（移植自 Gemini CLI @ 命令）解析成引用附到消息上。
 *  @ 前面不能是英文字母/数字/下划线/点/反斜杠/@（邮箱不弹），中文紧挨着可以；遇到空白和标点结束。
 *  v1.81 `$技能`：同一套，打 $ 列出启用的技能，选中补成 `$id `；后端 app/skill_mentions.py（移植自 Codex `$skill`）把正文给模型。
 *  $ 前是英文字母/数字/下划线/$ 不弹（US$5、$$）。
 *  v1.91 `@子助手`：打 @ 时第一行是“子助手”（没有工作区也列），选中补成 `@子助手 `；后端 app/agent_mentions.py（移植自 Gemini CLI
 *  @agent）认出来，提示模型用 delegate 交给子助手。英文别名 @agent / @subagent 同样认。
 *  排序（学 Codex file-search 的思路）：文件名开头 > 文件名包含 > 路径包含 > 按顺序出现；同分新的在前、路径短的在前。 */
import type { ProjectFile, Skill } from "./types";

export const MENTION_MAX = 5;
export type Sigil = "@" | "$";
export type MentionQuery = { start: number; end: number; query: string; sigil: Sigil };

const STOP = /[\s,;!?()[\]{}"'`，。；：！？、（）【】《》“”‘’「」]/;
const BLOCKED_BEFORE: Record<Sigil, RegExp> = { "@": /[A-Za-z0-9_.\\@]/, "$": /[A-Za-z0-9_$]/ };

export const AGENT_MENTION = "子助手";
const AGENT_ALIASES = ["子助手", "subagent", "agent"];
/** 正在打的 @xxx 对得上子助手吗（空 = 刚打 @，也列）。 */
export const agentMatches = (query: string) => { const q = query.trim().toLowerCase(); return AGENT_ALIASES.some((a) => a.startsWith(q)); };
const AGENT_RE = /(?<![A-Za-z0-9_.\\@])@(子助手|subagent|agent)(?![A-Za-z0-9_\-/\\]|\.[A-Za-z0-9_])/i;
const CODE_RE = /```[\s\S]*?(?:```|$)|`[^`\n]*`/g;
/** 消息里有没有点名子助手（同后端 agent_mentions 规则；代码里的不算）。 */
export const mentionsAgent = (text: string) => AGENT_RE.test(text.replace(CODE_RE, (m) => " ".repeat(m.length)));

/** 光标前正在打的 @ / $（只认 sigils 里的）。 */
export function mentionAt(text: string, caret: number, sigils: readonly Sigil[] = ["@"]): MentionQuery | null {
  if (caret < 0 || caret > text.length) return null;
  for (let i = caret - 1; i >= 0; i--) {
    const ch = text[i];
    if ((sigils as readonly string[]).includes(ch)) {
      const sigil = ch as Sigil;
      if (i > 0 && BLOCKED_BEFORE[sigil].test(text[i - 1])) return null;
      return { start: i, end: caret, query: text.slice(i + 1, caret), sigil };
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

/** 技能候选：id / 名字开头 > 包含 > 描述包含；停用的不列；同分保持技能页顺序。 */
export function rankSkills(skills: Skill[], query: string, max = MENTION_MAX): Skill[] {
  const q = query.toLowerCase().trim();
  const score = (s: Skill): number | null => {
    if (!q) return 0;
    const id = s.id.toLowerCase(), name = s.name.toLowerCase();
    if (id.startsWith(q) || name.startsWith(q)) return 300;
    if (id.includes(q) || name.includes(q)) return 200;
    return s.description.toLowerCase().includes(q) ? 100 : null;
  };
  return skills
    .flatMap((s, i) => { const sc = s.enabled === false ? null : score(s); return sc === null ? [] : [{ s, sc, i }]; })
    .sort((a, b) => b.sc - a.sc || a.i - b.i)
    .slice(0, max)
    .map((x) => x.s);
}

/** 带空白或标点的路径用双引号包（服务器认 `@"a b.txt"`）。 */
export const mentionToken = (path: string) => (STOP.test(path) && !path.includes('"') ? `@"${path}"` : `@${path}`);

/** 换掉正在打的 @xxx / $xxx → [新文字, 光标位置]。key = 文件路径 / 技能 id。 */
export function applyMention(text: string, m: MentionQuery, key: string): [string, number] {
  const rest = text.slice(m.end);
  const spaced = rest.startsWith(" ");
  const insert = (m.sigil === "$" ? `$${key}` : mentionToken(key)) + (spaced ? "" : " ");
  return [text.slice(0, m.start) + insert + rest, m.start + insert.length + (spaced ? 1 : 0)];
}
