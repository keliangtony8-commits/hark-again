// 技能页的纯逻辑：分组 + 搜索、页头摘要、起步模板。与 App features/me/skill_library.dart 同规则同措辞。
import type { Skill } from "../../lib/types";

/** 列表超过这么多条才给搜索框。 */
export const SKILL_SEARCH_FROM = 7;
export const fromBuiltin = (s: Partial<Skill>) => !!(s.builtin || s.customized);
export const isOn = (s: Partial<Skill>) => s.enabled !== false;

/** 按名称 / 用途 / 正文搜索（不分大小写），再分“我的”“内置”两组，各自保持服务器顺序。 */
export function filterSkills(list: Skill[], query: string) {
  const q = query.trim().toLowerCase();
  const shown = q ? list.filter((s) => `${s.name}\n${s.description}\n${s.body}`.toLowerCase().includes(q)) : list;
  return { mine: shown.filter((s) => !fromBuiltin(s)), builtin: shown.filter(fromBuiltin) };
}

/** “9 个技能 · 7 个在用 · 2 个自己写的”；空库是一句引导。 */
export function skillSummary(list: Skill[]) {
  if (!list.length) return "教我做事的固定方法";
  const on = list.filter(isOn).length;
  const mine = list.filter((s) => !fromBuiltin(s)).length;
  return [`${list.length} 个技能`, on === list.length ? "全部在用" : `${on} 个在用`, ...(mine ? [`${mine} 个自己写的`] : [])].join(" · ");
}

/** 起步模板：空的“我的”里给几颗，点了带内容进新建（没保存前什么都不存）。 */
export const SKILL_STARTERS: Pick<Skill, "name" | "description" | "body">[] = [
  { name: "写周报", description: "我让你写周报、总结一周进展时", body: "1. 先问我这周做了哪些事（或从对话和日程里找）\n2. 分“完成 / 进行中 / 下周计划”三段\n3. 每条一句话，整体不超过 200 字" },
  { name: "会议纪要", description: "我发来会议记录或录音转写，让你整理时", body: "1. 一句话写清会议目的\n2. 列出结论和待办（谁、做什么、什么时候）\n3. 有分歧的地方单独列出来" },
  { name: "每日复习", description: "我说“开始今天的复习”时", body: "1. 先问今天复习哪一科、有多少时间\n2. 按 25 分钟一段排计划\n3. 结束时出 3 道小题检查" },
];
