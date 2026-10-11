// 项目档案的小工具：网页版与 App models/resources.dart 同规则。
/** 项目档案最长多少字（和后端 project_brief.BRIEF_MAX 一致）。 */
export const BRIEF_MAX = 8000;

/** 档案第一行正文（跳过标题、空行和列表符号），给项目卡片当副标题。和 App Project.briefLine 同规则。 */
export function briefLine(brief = ""): string {
  for (const l of brief.split("\n")) {
    const t = l.trim().replace(/^([-*+]|\d+\.)\s+/, "");
    if (t && !t.startsWith("#")) return t;
  }
  return "";
}
