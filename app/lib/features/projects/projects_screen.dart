// 项目：长期的事各有自己的对话、文件和规则。列表 → 点开是项目内聊天。
// 列表是矮玻璃卡（图标 + 名称 + 规则一行 + “x 个对话 · 更新于…”）：手机一列，宽屏自动两列。
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/resource.dart';
import '../../models/resources.dart';
import '../../theme/app_theme.dart';
import '../../theme/tokens.dart';
import '../../ui/format.dart';
import '../../ui/kit.dart';
import '../../ui/motion.dart';
import '../../ui/sheets.dart';
import '../../shell/shell_page.dart';
import '../../ui/glass.dart';
import '../../shell/launch_composer.dart';
import '../chat/chat_scaffold.dart';
import 'project_files_sheet.dart';

class ProjectsScreen extends ConsumerWidget {
  const ProjectsScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final projects = ref.watch(projectsProvider);
    return Scaffold(
      backgroundColor: Colors.transparent, // 透出外壳的壁纸
      body: ShellPage(
        lead: GlassIconButton(icon: Icons.add_rounded, tooltip: '新项目', onTap: () => _create(context, ref)),
        child: LaunchComposer(child: Builder(builder: (context) => _list(context, ref, projects))),
      ),
    );
  }

  Widget _list(BuildContext context, WidgetRef ref, AsyncValue<List<Project>> projects) {
    final safe = MediaQuery.paddingOf(context); // 已含浮动顶栏的让位
    return AsyncBody<Project>(
      value: projects,
      onRetry: () => ref.invalidate(projectsProvider),
      empty: GlassCard(
        child: EmptyHint(
          icon: Icons.folder_outlined,
          title: '还没有项目',
          text: '考研复习、找实习、一次旅行……长期的事放进项目，资料和对话都在一起。',
          action: PillButton(label: '新建项目', icon: Icons.add_rounded, primary: true, onTap: () => _create(context, ref)),
        ),
      ),
      builder: (list) => GridView.builder(
        padding: const EdgeInsets.fromLTRB(Layout.gutter, 0, Layout.gutter, Sp.x5) + EdgeInsets.only(top: safe.top, bottom: safe.bottom),
        gridDelegate: const SliverGridDelegateWithMaxCrossAxisExtent(
          maxCrossAxisExtent: Layout.contentMax * 0.6,
          mainAxisSpacing: Layout.cardGap,
          crossAxisSpacing: Layout.cardGap,
          mainAxisExtent: _ProjectTile.height,
        ),
        itemCount: list.length,
        itemBuilder: (_, i) => FadeSlideIn(
          delay: Motion.stagger(i),
          child: _ProjectTile(project: list[i], onTap: () => context.push('/projects/${list[i].id}')),
        ),
      ),
    );
  }

  Future<void> _create(BuildContext context, WidgetRef ref) async {
    final v = await showFormSheet(
      context,
      title: '新项目',
      submit: '创建',
      fields: const [FieldSpec('name', '名称', hint: '比如：期末复习')],
    );
    if (v == null) return;
    final p = await ref.read(projectsProvider.notifier).create({'name': v['name']});
    if (context.mounted) context.push('/projects/${p.id}');
  }
}

class _ProjectTile extends StatelessWidget {
  const _ProjectTile({required this.project, required this.onTap});
  final Project project;
  final VoidCallback onTap;

  /// 固定高度：标题一行 + 规则（或档案）一行 + 统计一行，字体放大时也不跳版（1.3 倍有测试兜底）。
  static const height = 112.0;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final rules = project.rules.trim().split('\n').first;
    final line = rules.isNotEmpty ? rules : project.briefLine; // 规则优先，没有就用档案第一行
    final when = formatAgo(project.activeAt);
    final meta = [if (project.conversationCount > 0) '${project.conversationCount} 个对话' else '还没有对话', if (when.isNotEmpty) '更新于 $when'].join(' · ');
    return GlassCard(
      onTap: onTap,
      padding: const EdgeInsets.symmetric(horizontal: Sp.x4, vertical: Sp.x3),
      child: Row(
        children: [
          Container(
            width: A11y.minTap,
            height: A11y.minTap,
            alignment: Alignment.center,
            decoration: BoxDecoration(color: p.tile, borderRadius: BorderRadius.circular(Radii.md)),
            child: Text(project.emoji, style: context.text.titleLarge),
          ),
          const SizedBox(width: Sp.x3),
          Expanded(
            child: Column(
              mainAxisAlignment: MainAxisAlignment.center,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(project.name, style: context.text.titleMedium, maxLines: 1, overflow: TextOverflow.ellipsis),
                Text(line.isEmpty ? '还没有规则和档案' : line, style: context.text.bodySmall, maxLines: 1, overflow: TextOverflow.ellipsis),
                Text(meta, style: context.text.labelSmall, maxLines: 1, overflow: TextOverflow.ellipsis),
              ],
            ),
          ),
          Icon(Icons.chevron_right_rounded, color: p.text3),
        ],
      ),
    );
  }
}

class ProjectDetailScreen extends ConsumerWidget {
  const ProjectDetailScreen({super.key, required this.id});
  final String id;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final project = ref.watch(projectsProvider).value?.where((p) => p.id == id).firstOrNull;
    return ChatScaffold(
      projectId: id,
      historyTooltip: '项目对话',
      title: Text(project == null ? '项目' : '${project.emoji} ${project.name}', maxLines: 1, overflow: TextOverflow.ellipsis),
      actions: [
        IconButton(icon: const Icon(Icons.folder_open_rounded), tooltip: '项目文件', onPressed: () => showProjectFiles(context, id)),
        IconButton(icon: const Icon(Icons.article_outlined), tooltip: '规则与档案', onPressed: () => context.push('/projects/$id/brief')),
      ],
      suggestions: const ['总结一下这个项目现在的进度', '帮我列个下一步计划'],
    );
  }
}
