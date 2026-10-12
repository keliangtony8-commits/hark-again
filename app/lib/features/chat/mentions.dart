// 输入框里的 `@文件`：打 @ 弹出这段对话工作区里的文件（最近改的在前），边打边筛，点一下补成 `@路径 `。
// 只管“补全文字”：发出去以后由服务器 app/file_mentions.py（移植自 Gemini CLI @ 命令）把 @路径 解析成引用
// 附到消息上（一条规则，选择器选的、手打的都一样认；没选、打错的服务器也会按名字模糊找）。
// 规则和服务器一致：@ 前面不能是英文字母/数字/下划线/点/反斜杠/@（邮箱不弹），中文紧挨着可以；遇到空白和标点就结束。
// `$技能`（v1.81）：同一套候选条，打 $ 列出启用的技能，点一下补成 `$id `；服务器 app/skill_mentions.py（移植自 Codex
// `$skill` 显式调用）认出来，把技能正文直接给模型。$ 前面是英文字母/数字/下划线/$ 不弹（US$5、$$）。
// `@子助手`（v1.91）：打 @ 时候选条第一行是“子助手”，点一下补成 `@子助手 `；服务器 app/agent_mentions.py（移植自 Gemini CLI
// @agent）认出来，提示模型用 delegate 交给子助手做。没有工作区也能用（只列这一行）。规则同服务器：@agent / @subagent / @子助手。
// 排序学 Codex file-search 的思路（不移植 nucleo）：文件名开头 > 文件名包含 > 路径包含 > 按顺序出现的字母；同分看新旧、再看路径长短。
import 'package:flutter/material.dart';

import '../../models/resources.dart';
import '../../theme/app_theme.dart';
import '../../theme/tokens.dart';
import '../../ui/motion.dart';
import '../projects/project_files_sheet.dart' show projectFileIcon, projectFileLine;

/// 一次最多列几个候选（手机上不挡住整段对话）。
const mentionMax = 5;

/// 文件 `@`、技能 `$`。
const fileSigil = '@', skillSigil = r'$';

/// `@子助手` 写进消息的名字，以及服务器也认的英文别名（app/agent_mentions.py NAMES）。
const agentMention = '子助手';
const agentAliases = ['子助手', 'subagent', 'agent'];

/// 正在打的 @xxx 对得上子助手吗（空 = 刚打 @，也列）。
bool agentMatches(String query) {
  final q = query.trim().toLowerCase();
  return agentAliases.any((a) => a.startsWith(q));
}

final _agentRe = RegExp(r'(?<![A-Za-z0-9_.\\@])@(子助手|subagent|agent)(?![A-Za-z0-9_\-/\\]|\.[A-Za-z0-9_])', caseSensitive: false);
final _codeRe = RegExp(r'```[\s\S]*?(?:```|$)|`[^`\n]*`');

/// 消息里有没有点名子助手（和服务器同一条规则；代码里的不算）。
bool mentionsAgent(String text) => _agentRe.hasMatch(text.replaceAllMapped(_codeRe, (m) => ' ' * m[0]!.length));

/// 光标前正在打的 `@xxx` / `$xxx`：start = 符号的位置，query = 符号后面到光标的文字。
class MentionQuery {
  const MentionQuery(this.start, this.end, this.query, {this.sigil = fileSigil});
  final int start, end;
  final String query, sigil;
  bool get isSkill => sigil == skillSigil;
  @override
  bool operator ==(Object other) =>
      other is MentionQuery && other.start == start && other.end == end && other.query == query && other.sigil == sigil;
  @override
  int get hashCode => Object.hash(start, end, query, sigil);
}

final _stop = RegExp(r'[\s,;!?()\[\]{}"' "'" r'`，。；：！？、（）【】《》“”‘’「」]');
final _blockedBefore = {fileSigil: RegExp(r'[A-Za-z0-9_.\\@]'), skillSigil: RegExp(r'[A-Za-z0-9_$]')};

/// 光标（collapsed selection 的位置）前有没有正在打的 @ / $（[sigils] 里的）。没有 / 选中了一段 → null。
MentionQuery? mentionAt(String text, int caret, {Set<String> sigils = const {fileSigil}}) {
  if (caret < 0 || caret > text.length) return null;
  for (var i = caret - 1; i >= 0; i--) {
    final ch = text[i];
    if (sigils.contains(ch)) {
      if (i > 0 && _blockedBefore[ch]!.hasMatch(text[i - 1])) return null;
      return MentionQuery(i, caret, text.substring(i + 1, caret), sigil: ch);
    }
    if (_stop.hasMatch(ch)) return null;
  }
  return null;
}

/// 技能候选：id / 名字开头 > 包含 > 描述包含；同分保持技能页顺序。只给启用的。
List<Skill> rankSkills(List<Skill> skills, String query, {int max = mentionMax}) {
  final q = query.toLowerCase().trim();
  int? score(Skill s) {
    if (q.isEmpty) return 0;
    final id = s.id.toLowerCase(), name = s.name.toLowerCase();
    if (id.startsWith(q) || name.startsWith(q)) return 300;
    if (id.contains(q) || name.contains(q)) return 200;
    if (s.description.toLowerCase().contains(q)) return 100;
    return null;
  }

  final scored = <(Skill, int, int)>[
    for (final (i, s) in skills.indexed)
      if (s.enabled)
        if (score(s) case final int sc) (s, sc, i),
  ];
  scored.sort((a, b) => a.$2 != b.$2 ? b.$2.compareTo(a.$2) : a.$3.compareTo(b.$3));
  return [for (final s in scored.take(max)) s.$1];
}

/// 一个候选的分数：越大越靠前；不沾边 → null。
int? _score(ProjectFile f, String q) {
  if (q.isEmpty) return 0;
  final name = f.name.toLowerCase(), path = f.path.toLowerCase();
  if (name.startsWith(q)) return 400;
  if (name.contains(q)) return 300;
  if (path.contains(q)) return 200;
  var at = 0;
  for (final c in q.split('')) {
    at = path.indexOf(c, at);
    if (at < 0) return null;
    at++;
  }
  return 100;
}

/// 候选：分数 → 最近修改 → 路径短的在前，最多 [max] 个。
List<ProjectFile> rankMentions(List<ProjectFile> files, String query, {int max = mentionMax}) {
  final q = query.toLowerCase().trim();
  final scored = <(ProjectFile, int)>[
    for (final f in files)
      if (_score(f, q) case final int s) (f, s),
  ];
  scored.sort((a, b) {
    if (a.$2 != b.$2) return b.$2.compareTo(a.$2);
    final ta = a.$1.modified?.millisecondsSinceEpoch ?? 0, tb = b.$1.modified?.millisecondsSinceEpoch ?? 0;
    if (ta != tb) return tb.compareTo(ta);
    if (a.$1.path.length != b.$1.path.length) return a.$1.path.length.compareTo(b.$1.path.length);
    return a.$1.path.compareTo(b.$1.path);
  });
  return [for (final s in scored.take(max)) s.$1];
}

/// 路径写进消息的样子：带空白或标点的用双引号包（服务器认 `@"a b.txt"`）。
String mentionToken(String path) => _stop.hasMatch(path) && !path.contains('"') ? '@"$path"' : '@$path';

/// 把正在打的 @xxx / $xxx 换成 `@路径 ` / `$技能id `，返回新文字和光标位置。
(String, int) applyMention(String text, MentionQuery m, String path) {
  final token = '${m.isSkill ? '$skillSigil$path' : mentionToken(path)} ';
  final rest = text.substring(m.end);
  final insert = rest.startsWith(' ') ? token.trimRight() : token;
  final out = text.substring(0, m.start) + insert + rest;
  return (out, m.start + insert.length + (rest.startsWith(' ') ? 1 : 0));
}

/// 候选条里的一行（文件和技能共用一个列表组件）。
class MentionItem {
  const MentionItem({required this.key, required this.icon, required this.title, required this.subtitle, required this.semantic});
  final String key, title, subtitle, semantic;
  final IconData icon;

  factory MentionItem.file(ProjectFile f) =>
      MentionItem(key: f.path, icon: projectFileIcon(f.mime), title: f.name, subtitle: projectFileLine(f), semantic: '引用 ${f.path}');
  factory MentionItem.agent() => const MentionItem(
      key: agentMention, icon: Icons.call_split_rounded, title: agentMention, subtitle: '交给子助手去做，只把结论交回来', semantic: '交给子助手');
  factory MentionItem.skill(Skill s) =>
      MentionItem(key: s.id, icon: Icons.auto_awesome_rounded, title: s.name, subtitle: s.description, semantic: '用技能 ${s.name}');
}

/// 候选列表（输入胶囊顶部，和编辑条/命令条同一个位置）。空列表 → 一行说明（[empty]）。
class MentionList extends StatelessWidget {
  const MentionList({super.key, required this.items, required this.onPick, required this.empty, this.emptyIcon = Icons.alternate_email_rounded});
  final List<MentionItem> items;
  final ValueChanged<String> onPick;
  final String empty;
  final IconData emptyIcon;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final hint = context.text.bodySmall?.copyWith(color: p.text2);
    if (items.isEmpty) {
      return Padding(
        padding: const EdgeInsets.fromLTRB(Sp.x4, Sp.x2, Sp.x4, 0),
        child: Row(children: [
          Icon(emptyIcon, size: 16, color: p.text2),
          const SizedBox(width: Sp.x2),
          Expanded(child: Text(empty, style: hint, maxLines: 1, overflow: TextOverflow.ellipsis)),
        ]),
      );
    }
    return Padding(
      padding: const EdgeInsets.only(top: Sp.x1),
      child: Column(mainAxisSize: MainAxisSize.min, children: [
        for (final (i, it) in items.indexed)
          FadeSlideIn(
            key: ValueKey(it.key),
            delay: Motion.stagger(i),
            child: Pressable(
              onTap: () => onPick(it.key),
              semanticLabel: it.semantic,
              child: ConstrainedBox(
                constraints: const BoxConstraints(minHeight: A11y.minTap),
                child: Padding(
                  padding: const EdgeInsets.symmetric(horizontal: Sp.x4, vertical: Sp.x1),
                  child: Row(children: [
                    Icon(it.icon, size: 18, color: p.text2),
                    const SizedBox(width: Sp.x3),
                    Flexible(child: Text(it.title, style: context.text.bodyMedium, maxLines: 1, overflow: TextOverflow.ellipsis)),
                    const SizedBox(width: Sp.x2),
                    Expanded(child: Text(it.subtitle, style: hint, maxLines: 1, overflow: TextOverflow.ellipsis)),
                  ]),
                ),
              ),
            ),
          ),
      ]),
    );
  }
}
