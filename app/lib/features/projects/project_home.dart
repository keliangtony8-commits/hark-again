// 项目首屏（v1.10）：项目聊天还没打开任何对话时显示，代替通用的“今天想做点什么？”。
// 一个项目是长期的事，进来先看到“这是哪件事、上次聊到哪”：
//   项目字标 + 衬线名字 → 规则（或档案第一行）一行，点开规则与档案
//   → “最近的对话”最多 3 条（点开续聊；更多 → 打开项目对话抽屉）——双栏时历史已常驻左侧，不重复画
//   → “文件”（v1.11）：最近改过的 3 个项目文件（我和沙箱共用的文件夹），点开就看；全部/管理 → 文件抽屉；
//     空文件夹给一行“放点资料进来”——双栏也显示（文件不像历史那样常驻）
//   → “电脑”（v1.25）：项目沙盒的运行状态、内存、磁盘、正在运行的后台任务（features/computer/computer_section.dart）；
//   → 起步建议（新开一段）。
// 版式靠左、从让位线下往下排（不居中漂浮），和主页/项目列表同一套层级；入场 FadeSlideIn 错峰。
// 规则（取哪几条、副标题）是纯函数 projectRecent / projectLine，测试直接测。
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/resource.dart';
import '../../models/resources.dart';
import '../../theme/app_theme.dart';
import '../../theme/tokens.dart';
import '../../ui/adaptive.dart';
import '../../ui/format.dart';
import '../../ui/glass.dart';
import '../../ui/kit.dart';
import '../../ui/motion.dart';
import '../chat/chat_controller.dart';
import '../computer/computer_section.dart';
import 'project_files_sheet.dart';

export 'project_files_sheet.dart' show projectFileLine;

/// 首屏最多列几条最近对话。
const projectRecentMax = 3;

/// 最近的对话：置顶优先，其余按更新时间新→旧（没有时间的排后，顺序稳定），取前 [max] 条。
List<ConversationSummary> projectRecent(List<ConversationSummary> list, {int max = projectRecentMax}) {
  final epoch = DateTime.fromMillisecondsSinceEpoch(0);
  final indexed = list.indexed.toList()
    ..sort((a, b) {
      if (a.$2.pinned != b.$2.pinned) return a.$2.pinned ? -1 : 1;
      final t = (b.$2.updatedAt ?? epoch).compareTo(a.$2.updatedAt ?? epoch);
      return t != 0 ? t : a.$1.compareTo(b.$1);
    });
  return [for (final e in indexed.take(max)) e.$2];
}

/// 首屏最多列几个文件。
const projectFilesMax = 3;

/// 最近的文件：按修改时间新→旧（没有时间的排后，顺序稳定），取前 [max] 个。
List<ProjectFile> projectRecentFiles(List<ProjectFile> list, {int max = projectFilesMax}) {
  final epoch = DateTime.fromMillisecondsSinceEpoch(0);
  final indexed = list.indexed.toList()
    ..sort((a, b) {
      final t = (b.$2.modified ?? epoch).compareTo(a.$2.modified ?? epoch);
      return t != 0 ? t : a.$1.compareTo(b.$1);
    });
  return [for (final e in indexed.take(max)) e.$2];
}

/// 名字下面那一行：规则第一行，没有就档案第一行，都没有给一句引导。
String projectLine(Project p) {
  final rules = p.rules.trim().split('\n').first.trim();
  if (rules.isNotEmpty) return rules;
  final brief = p.briefLine;
  return brief.isNotEmpty ? brief : '还没有规则和档案，写下来助手每次都会照着做';
}

class ProjectHome extends ConsumerWidget {
  const ProjectHome({super.key, required this.projectId, required this.project, required this.suggestions, required this.onPick});
  final String projectId;
  final Project? project;
  final List<String> suggestions;
  final void Function(String) onPick;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final p = context.palette;
    final chat = ref.watch(chatProvider(projectId));
    final twoPane = context.window.twoPane; // 双栏：历史已在左边
    final all = chat.conversations;
    final recent = twoPane ? const <ConversationSummary>[] : projectRecent(all);
    final pr = project;
    final files = ref.watch(projectFilesProvider(projectId)).value; // 加载中/失败 → 不画这一节
    var i = 0; // 错峰序号
    Widget enter(Widget child) => FadeSlideIn(delay: Motion.stagger(i++), child: child);

    return Align(
      alignment: Alignment.topCenter,
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: Layout.contentMax),
        child: ListView(
          padding: const EdgeInsets.fromLTRB(Layout.gutter, Sp.x5, Layout.gutter, Sp.x5),
          children: [
            if (pr != null) ...[
              enter(Row(children: [
                Container(
                  width: Layout.projectMark,
                  height: Layout.projectMark,
                  alignment: Alignment.center,
                  decoration: BoxDecoration(color: context.tileFill, borderRadius: BorderRadius.circular(Radii.inner)),
                  child: Text(pr.emoji, style: context.text.titleLarge?.copyWith(fontSize: Fs.xl - 4)),
                ),
                const SizedBox(width: Sp.x4),
                Expanded(
                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Text(_meta(pr), style: context.text.labelSmall, maxLines: 1, overflow: TextOverflow.ellipsis),
                    const SizedBox(height: Sp.x1),
                    Text(pr.name, style: context.text.headlineMedium, maxLines: 2, overflow: TextOverflow.ellipsis),
                  ]),
                ),
              ])),
              const SizedBox(height: Sp.x3),
              enter(Pressable(
                onTap: () => context.push('/projects/$projectId/brief'),
                semanticLabel: '规则与档案',
                child: ConstrainedBox(
                    constraints: const BoxConstraints(minHeight: A11y.minTap),
                    child: Row(children: [
                      Expanded(
                        child: Text(projectLine(pr),
                            style: context.text.bodyMedium?.copyWith(color: p.text2), maxLines: 2, overflow: TextOverflow.ellipsis),
                      ),
                      const SizedBox(width: Sp.x2),
                      Icon(Icons.chevron_right_rounded, size: QuietAction.iconSize, color: p.text3),
                    ]),
                ),
              )),
            ],
            if (recent.isNotEmpty) ...[
              enter(SectionTitle('最近的对话',
                  trailing: all.length > recent.length
                      ? TextButton(
                          onPressed: () => Scaffold.maybeOf(context)?.openEndDrawer(),
                          child: Text('全部 ${all.length} 个'),
                        )
                      : null)),
              enter(GlassGroup(children: [
                for (final c in recent)
                  RowTile(
                    key: ValueKey('recent-${c.id}'),
                    icon: c.pinned ? Icons.push_pin_outlined : Icons.forum_outlined,
                    title: c.title,
                    trailing: c.updatedAt == null ? null : RowHint(formatAgo(c.updatedAt)),
                    onTap: () => ref.read(chatProvider(projectId).notifier).open(c.id),
                  ),
              ])),
            ],
            if (files != null) ...[
              enter(SectionTitle('文件',
                  trailing: files.isEmpty
                      ? null
                      : TextButton(
                          onPressed: () => showProjectFiles(context, projectId),
                          child: Text(files.length > projectFilesMax ? '全部 ${files.length} 个' : '管理'),
                        ))),
              enter(GlassGroup(children: [
                if (files.isEmpty)
                  RowTile(
                    key: const ValueKey('files-empty'),
                    icon: Icons.upload_file_rounded,
                    title: '放点资料进来',
                    subtitle: '上传后，在这个项目里聊天我都能直接读',
                    onTap: () => showProjectFiles(context, projectId),
                  )
                else
                  for (final f in projectRecentFiles(files))
                    RowTile(
                      key: ValueKey('file-${f.path}'),
                      icon: projectFileIcon(f.mime),
                      title: f.name,
                      subtitle: projectFileLine(f),
                      trailing: f.modified == null ? null : RowHint(formatAgo(f.modified)),
                      onTap: () => openProjectFile(ref, projectId, f),
                    ),
              ])),
            ],
            // 电脑（v1.25）：这个项目的沙盒在不在跑、在忙什么；加载中/无法连接服务器时整节不画。点状态块进详情页（v1.27）
            ComputerSection(
                ws: projectId, delay: Motion.stagger(i++), onOpen: () => context.push('/projects/$projectId/computer')),
            if (suggestions.isNotEmpty) ...[
              enter(SectionTitle(recent.isEmpty ? '从这里开始' : '或者新开一段')),
              enter(Wrap(spacing: Sp.x2, runSpacing: Sp.x2, children: [
                for (final s in suggestions) GlassChip(label: s, onTap: () => onPick(s)),
              ])),
            ],
          ],
        ),
      ),
    );
  }

  static String _meta(Project p) {
    final when = formatAgo(p.activeAt);
    return ['项目', if (p.conversationCount > 0) '${p.conversationCount} 个对话', if (when.isNotEmpty) '更新于 $when'].join(' · ');
  }
}
