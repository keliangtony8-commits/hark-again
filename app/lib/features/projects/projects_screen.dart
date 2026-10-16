// 项目：长期的事各有自己的一段对话、文件和规则。列表 → 点开就是那段对话（v2.95 项目 = 一段对话；都在一级外壳下）。
// 版式（v3.2.2 按 Hark 真机截图）：一项 = 占满整行的大字项目名（displaySmall，可折行）+ 下一行状态胶囊
// （= 那段对话的状态，服务器 status，规则在后端 conversation_status）；没有页头小标签、emoji、⋯，长按 = 项目菜单。
// “当前”的项目正文色，其余变灰（projectIsCurrent）。没有卡片网格、没有输入框：这一页只负责“选一件事”。
// 加载 / 空 / 出错 / 列表四态在同一个 FadeSwitcher 里交叉淡化，加载态是同高骨架，内容到了不跳版。
// 左上 + = 新建项目；它和项目页的 ≡（项目切换）是同一颗钮（MenuPlusHero，tag = projectLeadTag），进出项目时原地 morph。
// 新建与编辑都走 project_form.dart 的 showProjectForm，删除都走 deleteProject（列表菜单和项目内一致）。
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/resource.dart';
import '../../models/resources.dart';
import '../../theme/app_theme.dart';
import '../../theme/tokens.dart';
import '../../ui/kit.dart';
import '../../ui/motion.dart';
import '../../ui/sheets.dart';
import '../../shell/shell_page.dart';
import '../../ui/glass.dart';
import '../chat/status_capsule.dart';
import '../chat/chat_scaffold.dart';
import 'project_files_sheet.dart';
import 'project_form.dart';
import 'project_switcher.dart';

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

/// 项目的操作菜单（列表行 ⋯ / 长按、项目内的项目名药丸共用这一份）；onDeleted = 真的删了之后（项目内用来退出页面）。
Future<void> showProjectMenu(BuildContext context, WidgetRef ref, Project project, {VoidCallback? onDeleted}) =>
    showActionSheet<void>(
      context,
      title: '${project.emoji} ${project.name}',
      actions: [
        SheetAction(Icons.folder_open_rounded, '项目文件', onTap: () => showProjectFiles(context, project.id)),
        // v2.93 §Q：项目首屏不再画电脑一节，入口收进这里
        SheetAction(Icons.memory_rounded, '电脑', onTap: () => context.push('/projects/${project.id}/computer')),
        SheetAction(Icons.article_outlined, '规则与档案', onTap: () => context.push('/projects/${project.id}/brief')),
        SheetAction(Icons.edit_outlined, '编辑名称和图标', onTap: () => editProject(context, ref, project)),
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

/// v2.93 §Q 列表里哪些项目用正文色（其余变灰）：按最近活动排第一的那个，以及正在进行 / 等你回复的。
/// “已完成”和很久没动的退到背景；只看第一个会把另一个正在跑的项目也压灰，所以进行中 / 等你回复一律算当前。
/// 网页 projectHomeRules.ts 的 projectIsCurrent 同规则。
bool projectIsCurrent(int index, Project p) =>
    index == 0 || p.status == ConversationStatus.running || p.status == ConversationStatus.waiting;

class ProjectsScreen extends ConsumerWidget {
  const ProjectsScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final projects = ref.watch(projectsProvider);
    return Scaffold(
      backgroundColor: Colors.transparent, // 透出外壳的壁纸
      body: ShellPage(
        lead: MenuPlusHero(
          tag: projectLeadTag,
          plus: true,
          frame: (glyph) => GlassIconButton.glyph(glyph: glyph, tooltip: '新项目', onTap: () => createProject(context, ref)),
        ),
        child: FadeUnderCover(child: Builder(builder: (context) => _body(context, ref, projects))), // 进项目时列表淡出，钮留在原地
      ),
    );
  }

  Widget _body(BuildContext context, WidgetRef ref, AsyncValue<List<Project>> projects) {
    final safe = MediaQuery.paddingOf(context); // 已含浮动顶栏的让位
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
      content = Column(key: const ValueKey('loading'), children: [
        for (var i = 0; i < 3; i++)
          const Padding(padding: EdgeInsets.symmetric(vertical: Sp.x2), child: Shimmer(height: _ProjectRow.height - Sp.x4)),
      ]);
    } else if (list.isEmpty) {
      content = EmptyHint(
        key: const ValueKey('empty'),
        icon: Icons.folder_outlined,
        title: '还没有项目',
        text: '考研复习、找实习、一次旅行……长期的事放进项目，资料和对话都在一起。',
        action: PillButton(label: '新建项目', icon: Icons.add_rounded, primary: true, onTap: () => createProject(context, ref)),
      );
    } else {
      final sorted = byActivity(list);
      content = Column(key: const ValueKey('list'), crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        for (final (i, p) in sorted.indexed)
          FadeSlideIn(
            key: ValueKey(p.id),
            delay: Motion.stagger(i),
            child: _ProjectRow(
              project: p,
              current: projectIsCurrent(i, p),
              onTap: () => context.push('/projects/${p.id}'),
              onMenu: () => showProjectMenu(context, ref, p),
            ),
          ),
      ]);
    }
    return PullRefresh(
      onRefresh: () => ref.read(projectsProvider.notifier).reload(),
      child: Align(
        alignment: Alignment.topCenter,
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: Layout.contentMax),
          child: ListView(
            physics: const AlwaysScrollableScrollPhysics(),
            padding: const EdgeInsets.fromLTRB(Layout.gutter, 0, Layout.gutter, Sp.x5) + EdgeInsets.only(top: safe.top, bottom: safe.bottom),
            children: [
              const SizedBox(height: Layout.headTop - Sp.x3), // 内容让位线已含顶栏下 12
              FadeSwitcher(child: content),
            ],
          ),
        ),
      ),
    );
  }
}

/// 一行一个项目（v3.2.2 按 Hark 真机截图）：大字项目名占满整行、放不下就折行（最多 3 行），状态胶囊在名字下面另起一行。
/// 不画 emoji、不画 ⋯：emoji 留在项目内的项目名药丸上，菜单 = 长按（同项目内药丸那一份）。不是当前的项目名字用三级色。
class _ProjectRow extends StatelessWidget {
  const _ProjectRow({required this.project, required this.current, required this.onTap, required this.onMenu});
  final Project project;
  final bool current;
  final VoidCallback onTap, onMenu;

  /// 骨架行高（一行名字 + 胶囊）；真实行按内容自适应。
  static const height = 104.0;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final status = project.status;
    return Pressable(
      onTap: onTap,
      onLongPress: onMenu,
      semanticLabel: [project.name, if (status != null) status.label].join('，'),
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: Sp.x3),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
          Text(project.name,
              style: context.text.displaySmall?.copyWith(color: current ? p.text : p.text3),
              maxLines: 3,
              overflow: TextOverflow.ellipsis),
          if (status != null) ...[const SizedBox(height: Sp.x2), StatusCapsule(status)],
        ]),
      ),
    );
  }
}

/// 项目内（v2.95 项目 = 一段对话）：仍在一级外壳下（顶栏不消失）。顶栏下一枚项目名药丸（点开项目菜单），下面直接是这段对话；
/// 左上 ≡ = 项目切换（开着时转成 + = 新建项目）。回项目列表 = 再点一次顶栏“项目”。
class ProjectDetailScreen extends ConsumerWidget {
  const ProjectDetailScreen({super.key, required this.id});
  final String id;

  @override
  Widget build(BuildContext context, WidgetRef ref) => ChatScaffold(
        key: ValueKey(id), // 抽屉里换项目：整页换新（侧栏开合、抽屉状态不带到别的项目）
        projectId: id,
        title: ProjectPill(projectId: id, onDeleted: () {
          if (context.mounted) context.go('/projects');
        }),
      );
}
