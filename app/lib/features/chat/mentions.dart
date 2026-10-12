// 输入框里的 `@文件`：打 @ 弹出这段对话工作区里的文件（最近改的在前），边打边筛，点一下补成 `@路径 `。
// 只管“补全文字”：发出去以后由服务器 app/file_mentions.py（移植自 Gemini CLI @ 命令）把 @路径 解析成引用
// 附到消息上（一条规则，选择器选的、手打的都一样认；没选、打错的服务器也会按名字模糊找）。
// 规则和服务器一致：@ 前面不能是英文字母/数字/下划线/点/反斜杠/@（邮箱不弹），中文紧挨着可以；遇到空白和标点就结束。
// 排序学 Codex file-search 的思路（不移植 nucleo）：文件名开头 > 文件名包含 > 路径包含 > 按顺序出现的字母；同分看新旧、再看路径长短。
import 'package:flutter/material.dart';

import '../../models/resources.dart';
import '../../theme/app_theme.dart';
import '../../theme/tokens.dart';
import '../../ui/motion.dart';
import '../projects/project_files_sheet.dart' show projectFileIcon, projectFileLine;

/// 一次最多列几个候选（手机上不挡住整段对话）。
const mentionMax = 5;

/// 光标前正在打的 `@xxx`：start = @ 的位置，query = @ 后面到光标的文字。
class MentionQuery {
  const MentionQuery(this.start, this.end, this.query);
  final int start, end;
  final String query;
  @override
  bool operator ==(Object other) => other is MentionQuery && other.start == start && other.end == end && other.query == query;
  @override
  int get hashCode => Object.hash(start, end, query);
}

final _stop = RegExp(r'[\s,;!?()\[\]{}"' "'" r'`，。；：！？、（）【】《》“”‘’「」]');
final _blockedBefore = RegExp(r'[A-Za-z0-9_.\\@]');

/// 光标（collapsed selection 的位置）前有没有正在打的 @。没有 / 选中了一段 → null。
MentionQuery? mentionAt(String text, int caret) {
  if (caret < 0 || caret > text.length) return null;
  for (var i = caret - 1; i >= 0; i--) {
    final ch = text[i];
    if (ch == '@') {
      if (i > 0 && _blockedBefore.hasMatch(text[i - 1])) return null;
      return MentionQuery(i, caret, text.substring(i + 1, caret));
    }
    if (_stop.hasMatch(ch)) return null;
  }
  return null;
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

/// 把正在打的 @xxx 换成 `@路径 `，返回新文字和光标位置。
(String, int) applyMention(String text, MentionQuery m, String path) {
  final token = '${mentionToken(path)} ';
  final rest = text.substring(m.end);
  final insert = rest.startsWith(' ') ? token.trimRight() : token;
  final out = text.substring(0, m.start) + insert + rest;
  return (out, m.start + insert.length + (rest.startsWith(' ') ? 1 : 0));
}

/// 候选列表（输入胶囊顶部，和编辑条/命令条同一个位置）。空列表 → 一行说明。
class MentionList extends StatelessWidget {
  const MentionList({super.key, required this.files, required this.onPick, this.loading = false});
  final List<ProjectFile> files;
  final ValueChanged<ProjectFile> onPick;
  final bool loading;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final hint = context.text.bodySmall?.copyWith(color: p.text2);
    if (files.isEmpty) {
      return Padding(
        padding: const EdgeInsets.fromLTRB(Sp.x4, Sp.x2, Sp.x4, 0),
        child: Row(children: [
          Icon(Icons.alternate_email_rounded, size: 16, color: p.text2),
          const SizedBox(width: Sp.x2),
          Expanded(child: Text(loading ? '正在找文件…' : '没有对得上的文件 · 发出去我也会按名字再找一次', style: hint, maxLines: 1, overflow: TextOverflow.ellipsis)),
        ]),
      );
    }
    return Padding(
      padding: const EdgeInsets.only(top: Sp.x1),
      child: Column(mainAxisSize: MainAxisSize.min, children: [
        for (final (i, f) in files.indexed)
          FadeSlideIn(
            key: ValueKey(f.path),
            delay: Motion.stagger(i),
            child: Pressable(
              onTap: () => onPick(f),
              semanticLabel: '引用 ${f.path}',
              child: ConstrainedBox(
                constraints: const BoxConstraints(minHeight: A11y.minTap),
                child: Padding(
                  padding: const EdgeInsets.symmetric(horizontal: Sp.x4, vertical: Sp.x1),
                  child: Row(children: [
                    Icon(projectFileIcon(f.mime), size: 18, color: p.text2),
                    const SizedBox(width: Sp.x3),
                    Flexible(child: Text(f.name, style: context.text.bodyMedium, maxLines: 1, overflow: TextOverflow.ellipsis)),
                    const SizedBox(width: Sp.x2),
                    Expanded(
                      child: Text(projectFileLine(f), style: hint, maxLines: 1, overflow: TextOverflow.ellipsis),
                    ),
                  ]),
                ),
              ),
            ),
          ),
      ]),
    );
  }
}
