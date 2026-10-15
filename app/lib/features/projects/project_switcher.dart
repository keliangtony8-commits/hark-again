// v2.95 项目 = 一段对话：项目页的两件小东西，规格见 docs/devlog.md「2026-10-15 v2.95」。
// ProjectSwitcher：项目页左上 ≡ 打开的“项目切换”栏——列出所有项目（按最近活动，行尾项目状态胶囊，当前项目高亮），
//   点一个就换到那个项目的聊天。和主聊天“≡ 打开历史对话”同构：抽屉 = 同层级切换，左上钮在抽屉开着时转成 + = 新建项目。
//   手机装进抽屉（从药丸那一行下面滑出，左上钮不被盖住才能 morph）；双栏时常驻左侧（docked，标题旁自带 +）。
// ProjectPill：顶栏下那一行（ChatScaffold header）在项目里写的东西——项目名药丸（emoji 名字 ▾），进页时 DropIn 落下一次，
//   点它 = 项目菜单（showProjectMenu：文件 / 电脑 / 规则与档案 / 编辑 / 删除，和列表行 ⋯ 同一份）。主聊天那一行仍写对话标题。
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/resource.dart';
import '../../models/resources.dart';
import '../../theme/app_theme.dart';
import '../../theme/tokens.dart';
import '../../ui/glass.dart';
import '../../ui/motion.dart';
import '../chat/status_capsule.dart';
import 'projects_screen.dart';

class ProjectSwitcher extends ConsumerWidget {
  const ProjectSwitcher({super.key, required this.currentId, this.docked = false});
  final String currentId;

  /// true = 常驻侧栏；false = 抽屉（换项目后关掉抽屉）
  final bool docked;

  static Widget drawer(BuildContext context, String currentId) =>
      Drawer(backgroundColor: context.palette.bg, child: ProjectSwitcher(currentId: currentId));

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final p = context.palette;
    final list = byActivity(ref.watch(projectsProvider).value ?? const <Project>[]);
    void pick(Project project) {
      if (!docked) Navigator.pop(context);
      if (project.id != currentId) context.go('/projects/${project.id}');
    }

    return Material(
      color: p.bg,
      child: SafeArea(
        right: false,
        child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(Sp.x5, Sp.x2, Sp.x2, Sp.x1),
            child: Row(children: [
              Expanded(child: Text('项目', style: context.text.titleLarge)),
              // 手机抽屉：新建项目 = 左上那颗转成 + 的钮（ChatScaffold），这里不重复；高度照占，标题不跳
              if (docked)
                IconButton(icon: const Icon(Icons.add_rounded), tooltip: '新项目', color: p.text, onPressed: () => createProject(context, ref))
              else
                const SizedBox(height: A11y.minTap),
            ]),
          ),
          Expanded(
            child: ListView(
              padding: const EdgeInsets.fromLTRB(Sp.x2, 0, Sp.x2, Sp.x5),
              children: [
                for (final (i, project) in list.indexed)
                  FadeSlideIn(
                    key: ValueKey(project.id),
                    delay: Motion.stagger(i),
                    child: _Row(project: project, current: project.id == currentId, onTap: () => pick(project)),
                  ),
              ],
            ),
          ),
        ]),
      ),
    );
  }
}

class _Row extends StatelessWidget {
  const _Row({required this.project, required this.current, required this.onTap});
  final Project project;
  final bool current;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final status = project.status;
    return AnimatedContainer(
      duration: Motion.base,
      curve: Motion.ease,
      decoration: BoxDecoration(color: current ? context.tileFill : null, borderRadius: BorderRadius.circular(Radii.inner)),
      child: InkWell(
        borderRadius: BorderRadius.circular(Radii.inner),
        onTap: onTap,
        child: Semantics(
          selected: current,
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: Sp.x3, vertical: Sp.x3),
            child: Row(children: [
              Text(project.emoji, style: context.text.titleMedium),
              const SizedBox(width: Sp.x3),
              Expanded(
                child: Text(project.name,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: context.text.titleMedium?.copyWith(fontWeight: current ? Weights.strong : null)),
              ),
              if (status != null) ...[const SizedBox(width: Sp.x2), StatusCapsule(status)],
            ]),
          ),
        ),
      ),
    );
  }
}

/// 项目页顶栏下那一行：项目名药丸，点开项目菜单。[onDeleted]：在菜单里删掉了这个项目（项目页用来退回列表）。
class ProjectPill extends ConsumerWidget {
  const ProjectPill({super.key, required this.projectId, this.onDeleted});
  final String projectId;
  final VoidCallback? onDeleted;

  static const maxWidth = 280.0;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final p = context.palette;
    final project = ref.watch(projectsProvider).value?.where((x) => x.id == projectId).firstOrNull;
    final label = project == null ? '项目' : '${project.emoji} ${project.name}';
    return RepaintBoundary(
      child: DropIn(
        shown: true, // 一挂上就从上方落下来（进项目那一下）；之后常驻
        child: Semantics(
          button: true,
          label: '项目菜单：$label',
          excludeSemantics: true,
          child: Pressable(
            onTap: project == null ? null : () => showProjectMenu(context, ref, project, onDeleted: onDeleted),
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: maxWidth),
              child: GlassSurface(
                radius: Radii.full,
                blur: true, // 浮在滚动的文字上：真模糊才读得清
                padding: const EdgeInsets.fromLTRB(Sp.x4, Sp.x2, Sp.x3, Sp.x2),
                child: Row(mainAxisSize: MainAxisSize.min, children: [
                  Flexible(
                    child: Text(label,
                        maxLines: 1, overflow: TextOverflow.ellipsis, style: context.text.labelLarge?.copyWith(color: p.text, height: 1.2)),
                  ),
                  const SizedBox(width: Sp.x1),
                  Icon(Icons.expand_more_rounded, size: Fs.md, color: p.text3),
                ]),
              ),
            ),
          ),
        ),
      ),
    );
  }
}
