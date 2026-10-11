// 技能页的纯逻辑（无 UI，单测直接测）：分组 + 搜索、页头摘要、起步模板。
// 网页版同名逻辑在 frontend/src/features/me/skillLibrary.ts，两边措辞保持一致。
import '../../models/resources.dart';

/// 列表超过这么多条才给搜索框（少的时候一眼就看完，搜索框只是噪音）。
const skillSearchFrom = 7;

/// 按名称 / “什么时候用” / 正文搜索（不分大小写），再分成“我的”和“内置”两组，各自保持服务器顺序。
({List<Skill> mine, List<Skill> builtin}) filterSkills(List<Skill> list, String query) {
  final q = query.trim().toLowerCase();
  bool hit(Skill s) => q.isEmpty || '${s.name}\n${s.description}\n${s.body}'.toLowerCase().contains(q);
  final shown = [for (final s in list) if (hit(s)) s];
  return (
    mine: [for (final s in shown) if (!s.fromBuiltin) s],
    builtin: [for (final s in shown) if (s.fromBuiltin) s],
  );
}

/// 页头小标签：“9 个技能 · 7 个在用 · 2 个自己写的”；空库是一句引导。
String skillSummary(List<Skill> list) {
  if (list.isEmpty) return '教我做事的固定方法';
  final on = list.where((s) => s.enabled).length;
  final mine = list.where((s) => !s.fromBuiltin).length;
  return [
    '${list.length} 个技能',
    on == list.length ? '全部在用' : '$on 个在用',
    if (mine > 0) '$mine 个自己写的',
  ].join(' · ');
}

/// 起步模板：空的“我的技能”里给几颗，点一下带着内容进新建页（还没保存，改完再存）。
class SkillStarter {
  const SkillStarter(this.name, this.description, this.body);
  final String name, description, body;
}

const skillStarters = [
  SkillStarter('写周报', '我让你写周报、总结一周进展时', '1. 先问我这周做了哪些事（或从对话和日程里找）\n2. 分“完成 / 进行中 / 下周计划”三段\n3. 每条一句话，整体不超过 200 字'),
  SkillStarter('会议纪要', '我发来会议记录或录音转写，让你整理时', '1. 一句话写清会议目的\n2. 列出结论和待办（谁、做什么、什么时候）\n3. 有分歧的地方单独列出来'),
  SkillStarter('每日复习', '我说“开始今天的复习”时', '1. 先问今天复习哪一科、有多少时间\n2. 按 25 分钟一段排计划\n3. 结束时出 3 道小题检查'),
];
