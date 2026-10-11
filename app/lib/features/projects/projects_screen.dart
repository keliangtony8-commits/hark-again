// 项目：长期的事各有自己的对话、文件和规则。列表 → 点开是项目内聊天。
// 版式（v0.73）：和主页、“我的”同一套层级——小标签（几个项目 · 最近活动）+ 衬线大标题“项目”，
// 下面是矮玻璃卡网格（手机一列，宽屏自动多列）。加载 / 空 / 出错 / 列表四态在同一个 FadeSwitcher 里交叉淡化，
// 加载态是同形骨架（和卡片同高同圆角），内容到了不跳版。卡片右侧 ⋯（或长按）= 编辑 / 规则与档案 / 文件 / 删除。
// 新建与编辑都走 project_form.dart 的 showProjectForm，删除都走 deleteProject（列表菜单和项目内一致）。
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
import 'project_form.dart';
import 'project_home.dart';

/// 新建项目并直接进去。
Future<void> createProject(BuildContext context, WidgetRef ref) async {
  final body = await showProjectForm(context);
  if (body == null) return;
  final p = await ref.read(projectsProvider.notifier).create(body);
  if (context.mounted) context.push('/projects/${p.id}');
}

/// 改名称 / 图标；什么都没改就不发请求。
Future<void> editProject(BuildContext context, WidgetRef ref, Project project) async {
  final body = await showProjectForm(context, project: project);
  if (body == null || body.isEmpty) return;
  await ref.read(projectsProvider.notifier).patch(project.id, body);
}

/// 删除前确认（对话、文件、档案一起没）；返回是否真的删了。
Future<bool> deleteProject(BuildContext context, WidgetRef ref, Project project) async {
  final ok = await confirmDanger(context, title: '删除“${project.name}”？', text: '项目里的对话、文件和档案会一起删除，不能恢复。');
  if (!ok) return false;
  await ref.read(projectsProvider.notifier).remove(project.id);
  return true;
}

/// 项目的操作菜单（列表卡 ⋯ / 长按、项目内标题栏 ⋯ 共用这一份）；onDeleted = 真的删了之后（项目内用来退出页面）。
Future<void> showProjectMenu(BuildContext context, WidgetRef ref, Project project, {VoidCallback? onDeleted}) =>
    showActionSheet<void>(
      context,
      title: '${project.emoji} ${project.name}',
      actions: [
        SheetAction(Icons.edit_outlined, '编辑名称和图标', onTap: () => editProject(context, ref, project)),
        SheetAction(Icons.article_outlined, '规则与档案', onTap: () => context.push('/projects/${project.id}/brief')),
        SheetAction(Icons.folder_open_rounded, '项目文件', onTap: () => showProjectFiles(context, project.id)),
        SheetAction(Icons.delete_outline_rounded, '删除项目', danger: true, onTap: () async {
          if (await deleteProject(context, ref, project)) onDeleted?.call();
        }),
      ],
    );

/// 最近有动静的排前面（项目本身或其中任一对话的最后更新）。
List<Project> byActivity(List<Project> list) {
  final epoch = DateTime.fromMillisecondsSinceEpoch(0);
  return [...list]..sort((a, b) => (b.activeAt ?? epoch).compareTo(a.activeAt ?? epoch));
}

class ProjectsScreen extends ConsumerWidget {
  const ProjectsScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final projects = ref.watch(projectsProvider);
    return Scaffold(
      backgroundColor: Colors.transparent, // 透出外壳的壁纸
      body: ShellPage(
        lead: GlassIconButton(icon: Icons.add_rounded, tooltip: '新项目', onTap: () => createProject(context, ref)),
        child: LaunchComposer(child: Builder(builder: (context) => _body(context, ref, projects))),
      ),
    );
  }

  Widget _body(BuildContext context, WidgetRef ref, AsyncValue<List<Project>> projects) {
    final safe = MediaQuery.paddingOf(context); // 已含浮动顶栏和底部输入胶囊的让位
    final list = projects.value;
    final Widget content;
    if (list == null && projects.hasError) {
      content = EmptyHint(
        key: const ValueKey('error'),
        icon: Icons.cloud_off_rounded,
        title: '加载失败',
        text: '${projects.error}',
        action: OutlinedButton(onPressed: () => ref.invalidate(projectsProvider), child: const Text('重试')),
      );
    } else if (list == null) {
      content = _Grid(key: const ValueKey('loading'), children: [
        for (var i = 0; i < 3; i++) const Shimmer(height: _ProjectTile.height, radius: Radii.card),
      ]);
    } else if (list.isEmpty) {
      content = GlassCard(
        key: const ValueKey('empty'),
        child: EmptyHint(
          icon: Icons.folder_outlined,
          title: '还没有项目',
          text: '考研复习、找实习、一次旅行……长期的事放进项目，资料和对话都在一起。',
          action: PillButton(label: '新建项目', icon: Icons.add_rounded, primary: true, onTap: () => createProject(context, ref)),
        ),
      );
    } else {
      final sorted = byActivity(list);
      content = _Grid(key: const ValueKey('list'), children: [
        for (final (i, p) in sorted.indexed)
          FadeSlideIn(
            key: ValueKey(p.id),
            delay: Motion.stagger(i),
            child: _ProjectTile(
              project: p,
              onTap: () => context.push('/projects/${p.id}'),
              onMenu: () => showProjectMenu(context, ref, p),
            ),
          ),
      ]);
    }
    return PullRefresh(
      onRefresh: () => ref.read(projectsProvider.notifier).reload(),
      child: ListView(
        physics: const AlwaysScrollableScrollPhysics(),
        padding: const EdgeInsets.fromLTRB(Layout.gutter, 0, Layout.gutter, Sp.x5) + EdgeInsets.only(top: safe.top, bottom: safe.bottom),
        children: [
          _Header(projects: list),
          const SizedBox(height: Sp.x5),
          FadeSwitcher(child: content),
        ],
      ),
    );
  }

}

/// 页头：小标签一行 + 衬线大标题（和主页问候、“我的”同一层级）。标签内容变化时换一下，不跳高度。
class _Header extends StatelessWidget {
  const _Header({required this.projects});
  final List<Project>? projects;

  /// “3 个项目 · 最近 今天 09:12”；还在加载时是空串（行高照占）。
  static String summary(List<Project>? list) {
    if (list == null) return '';
    if (list.isEmpty) return '长期的事放这里';
    final latest = byActivity(list).first.activeAt;
    final when = latest == null ? '' : formatAgo(latest);
    return ['${list.length} 个项目', if (when.isNotEmpty) '最近 $when'].join(' · ');
  }

  @override
  Widget build(BuildContext context) {
    final line = summary(projects);
    return FadeSlideIn(
      child: Padding(
        padding: const EdgeInsets.only(top: Layout.headTop - Sp.x3), // 内容让位线已含顶栏下 12
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          SwapSwitcher(child: Text(line, key: ValueKey(line), style: context.text.labelSmall)),
          const SizedBox(height: Sp.x2),
          Text('项目', style: context.text.displayMedium),
        ]),
      ),
    );
  }
}

/// 不滚动的网格（项目不会多到要懒加载）：列数和 SliverGridDelegateWithMaxCrossAxisExtent 一样按最大宽度算，
/// 每格固定高度；骨架和列表共用，所以加载态和内容同形。
class _Grid extends StatelessWidget {
  const _Grid({super.key, required this.children});
  final List<Widget> children;
  static const maxExtent = Layout.contentMax * 0.6;

  @override
  Widget build(BuildContext context) => LayoutBuilder(builder: (context, c) {
        final cols = ((c.maxWidth + Layout.cardGap) / (maxExtent + Layout.cardGap)).ceil().clamp(1, 4);
        return Column(children: [
          for (var r = 0; r * cols < children.length; r++) ...[
            if (r > 0) const SizedBox(height: Layout.cardGap),
            Row(children: [
              for (var k = 0; k < cols; k++) ...[
                if (k > 0) const SizedBox(width: Layout.cardGap),
                Expanded(
                  child: SizedBox(
                    height: _ProjectTile.height,
                    child: r * cols + k < children.length ? children[r * cols + k] : null,
                  ),
                ),
              ],
            ]),
          ],
        ]);
      });
}

class _ProjectTile extends StatelessWidget {
  const _ProjectTile({required this.project, required this.onTap, required this.onMenu});
  final Project project;
  final VoidCallback onTap, onMenu;

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
      onLongPress: onMenu,
      padding: const EdgeInsets.fromLTRB(Sp.x4, Sp.x3, Sp.x1, Sp.x3),
      child: Row(
        children: [
          Container(
            width: A11y.minTap,
            height: A11y.minTap,
            alignment: Alignment.center,
            decoration: BoxDecoration(color: context.tileFill, borderRadius: BorderRadius.circular(Radii.tile)),
            child: Text(project.emoji, style: context.text.titleLarge),
          ),
          const SizedBox(width: Sp.x3),
          Expanded(
            child: Column(
              mainAxisAlignment: MainAxisAlignment.center,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(project.name, style: context.text.titleMedium, maxLines: 1, overflow: TextOverflow.ellipsis),
                const SizedBox(height: 2),
                Text(line.isEmpty ? '还没有规则和档案' : line,
                    style: context.text.bodySmall?.copyWith(color: p.text2), maxLines: 1, overflow: TextOverflow.ellipsis),
                const SizedBox(height: 2),
                Text(meta, style: context.text.labelSmall, maxLines: 1, overflow: TextOverflow.ellipsis),
              ],
            ),
          ),
          QuietAction(icon: const Icon(Icons.more_horiz_rounded), tooltip: '更多', onPressed: onMenu),
        ],
      ),
    );
  }
}

/// 项目内：项目聊天。标题栏只留“项目对话”和一颗 ⋯（文件 / 规则与档案 / 编辑 / 删除，与列表菜单同一份）——
/// 以前四颗图标挤在一起把标题压短（v1.10）。没打开对话时是项目首屏 ProjectHome。
class ProjectDetailScreen extends ConsumerWidget {
  const ProjectDetailScreen({super.key, required this.id});
  final String id;
  static const suggestions = ['总结一下这个项目现在的进度', '帮我列个下一步计划'];

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final project = ref.watch(projectsProvider).value?.where((p) => p.id == id).firstOrNull;
    return ChatScaffold(
      projectId: id,
      historyTooltip: '项目对话',
      title: Text(project == null ? '项目' : '${project.emoji} ${project.name}', maxLines: 1, overflow: TextOverflow.ellipsis),
      actions: [
        if (project != null)
          IconButton(
            icon: const Icon(Icons.more_horiz_rounded),
            tooltip: '项目菜单',
            onPressed: () => showProjectMenu(context, ref, project, onDeleted: () {
              if (context.mounted && context.canPop()) context.pop();
            }),
          ),
      ],
      suggestions: suggestions,
      empty: (context, send) => ProjectHome(projectId: id, project: project, suggestions: suggestions, onPick: send),
    );
  }
}
