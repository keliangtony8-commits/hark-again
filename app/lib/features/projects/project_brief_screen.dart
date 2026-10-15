// 项目的“规则与档案”页（/projects/:id/brief）。
// 规则 = 用户给的几句硬要求（表单弹层改）；档案 = 项目的长期记忆（Markdown），助手在对话里用 project_brief 工具自己维护，
// 用户也能在这里直接改。数据都在 projectsProvider 的 Project 上：进页先静默 reload 一次（助手可能刚改过），
// 保存走 PATCH，服务器盖“谁改的/何时”的戳。查看 ↔ 编辑用 SwapSwitcher 切换；有没保存的改动时返回要确认。
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api.dart';
import '../../core/resource.dart';
import '../../models/resources.dart';
import '../../theme/app_theme.dart';
import '../../theme/tokens.dart';
import '../../ui/format.dart';
import '../../ui/kit.dart';
import '../../ui/sub_page.dart';
import '../../ui/markdown.dart';
import '../../ui/motion.dart';
import '../../ui/sheets.dart';

class ProjectBriefScreen extends ConsumerStatefulWidget {
  const ProjectBriefScreen({super.key, required this.id});
  final String id;

  @override
  ConsumerState<ProjectBriefScreen> createState() => _ProjectBriefScreenState();
}

class _ProjectBriefScreenState extends ConsumerState<ProjectBriefScreen> {
  final _text = TextEditingController();
  bool _editing = false, _busy = false;

  @override
  void initState() {
    super.initState();
    _text.addListener(() => setState(() {}));
    Future.microtask(() async {
      try {
        await ref.read(projectsProvider.notifier).reload();
      } catch (_) {} // 离线：照常显示缓存里的档案
    });
  }

  @override
  void dispose() {
    _text.dispose();
    super.dispose();
  }

  Project? get _project => ref.read(projectsProvider).value?.where((p) => p.id == widget.id).firstOrNull;

  bool get _dirty => _editing && _text.text.trim() != (_project?.brief ?? '');

  void _startEdit() {
    _text.text = _project?.brief ?? '';
    setState(() => _editing = true);
  }

  Future<void> _save() async {
    if (_text.text.trim().length > briefMaxChars) {
      showToast(context, '档案最多 $briefMaxChars 字');
      return;
    }
    setState(() => _busy = true);
    try {
      await ref.read(projectsProvider.notifier).patch(widget.id, {'brief': _text.text});
      if (mounted) setState(() => _editing = false);
    } on ApiError catch (e) {
      if (mounted) showToast(context, e.message);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _cancel() async {
    if (_dirty && !await confirmDanger(context, title: '放弃这次改动？', text: '档案会保持原样。', action: '放弃')) return;
    if (mounted) setState(() => _editing = false);
  }

  Future<void> _editRules(Project project) async {
    final v = await showFormSheet(
      context,
      title: '项目规则',
      subtitle: '在这个项目里我每次都会遵守',
      fields: [FieldSpec('rules', '规则', hint: '比如：回答都用英文；代码用 Python', initial: project.rules, lines: 4, required: false)],
    );
    if (v == null) return;
    try {
      await ref.read(projectsProvider.notifier).patch(project.id, {'rules': v['rules']});
    } on ApiError catch (e) {
      if (mounted) showToast(context, e.message);
    }
  }

  @override
  Widget build(BuildContext context) {
    final project = ref.watch(projectsProvider).value?.where((p) => p.id == widget.id).firstOrNull;
    return PopScope(
      canPop: !_dirty,
      onPopInvokedWithResult: (didPop, _) {
        if (!didPop) _cancel();
      },
      child: SubPage(
        title: const Text('规则与档案'),
        actions: [
          if (project != null)
            Padding(
              padding: const EdgeInsets.only(right: Sp.x2),
              child: SwapSwitcher(
                child: _editing
                    ? Row(
                        key: const ValueKey('edit'),
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          TextButton(onPressed: _busy ? null : _cancel, child: const Text('取消')),
                          FilledButton(onPressed: _busy || !_dirty ? null : _save, child: const Text('保存')),
                        ],
                      )
                    : TextButton.icon(
                        key: const ValueKey('view'),
                        onPressed: _startEdit,
                        icon: const Icon(Icons.edit_outlined, size: Fs.lg - 2),
                        label: const Text('编辑档案'),
                      ),
              ),
            ),
        ],
        body: project == null
            ? const PageBody(children: [SkeletonList()])
            : PageBody(
                children: [
                  ListGroup(
                    children: [
                      ListRow(
                        icon: Icons.tune_rounded,
                        title: '项目规则',
                        subtitle: project.rules.trim().isEmpty ? '还没有：比如“回答都用英文”' : project.rules.trim(),
                        trailing: const Icon(Icons.chevron_right_rounded),
                        onTap: () => _editRules(project),
                      ),
                    ],
                  ),
                  const SizedBox(height: Sp.x5),
                  SectionTitle('项目档案', trailing: _Stamp(project: project)),
                  SwapSwitcher(
                    child: _editing
                        ? _Editor(key: const ValueKey('editor'), controller: _text, enabled: !_busy)
                        : _Viewer(key: ValueKey('view:${project.briefUpdatedAt}'), project: project, onWrite: _startEdit),
                  ),
                  const SizedBox(height: Sp.x3),
                  Text('这是我在此项目中的长期记忆：目标、已定决策、重要文件与固定流程。我会随工作自动更新，你也可以直接编辑。', style: context.text.bodySmall?.copyWith(color: context.palette.text3)),
                ],
              ),
      ),
    );
  }
}

/// “助手更新于 3 分钟前 / 你编辑于 …”：让人一眼看出档案是不是助手刚动过。
class _Stamp extends StatelessWidget {
  const _Stamp({required this.project});
  final Project project;

  @override
  Widget build(BuildContext context) {
    final when = formatAgo(project.briefUpdatedAt);
    if (when.isEmpty || project.brief.isEmpty) return const SizedBox.shrink();
    final who = project.briefBy == 'assistant' ? '助手更新于' : '你编辑于';
    return Pill('$who $when', strong: project.briefBy == 'assistant');
  }
}

class _Viewer extends StatelessWidget {
  const _Viewer({super.key, required this.project, required this.onWrite});
  final Project project;
  final VoidCallback onWrite;

  @override
  Widget build(BuildContext context) {
    if (project.brief.trim().isEmpty) {
      return AppCard(
        child: EmptyHint(
          icon: Icons.article_outlined,
          title: '档案还是空的',
          text: '在项目里聊聊你的目标，我会自己建一份；也可以现在先写几句。',
          action: FilledButton.tonalIcon(onPressed: onWrite, icon: const Icon(Icons.edit_outlined), label: const Text('自己写')),
        ),
      );
    }
    return FadeSlideIn(
      child: AppCard(
        child: SizedBox(width: double.infinity, child: AppMarkdown(project.brief)),
      ),
    );
  }
}

class _Editor extends StatelessWidget {
  const _Editor({super.key, required this.controller, required this.enabled});
  final TextEditingController controller;
  final bool enabled;

  @override
  Widget build(BuildContext context) {
    final n = controller.text.trim().length;
    return TextField(
      controller: controller,
      enabled: enabled,
      autofocus: true,
      minLines: 14,
      maxLines: null,
      style: context.text.bodyMedium?.copyWith(fontFamily: 'monospace', fontSize: Fs.sm, height: Fs.prose),
      decoration: InputDecoration(
        alignLabelWithHint: true,
        hintText: '## 目标\n12 月考研，目标 211 软件工程\n\n## 固定做法\n- 每晚复盘当天错题',
        helperText: 'Markdown，用小标题分段',
        counterText: '$n / $briefMaxChars',
        counterStyle: n > briefMaxChars ? TextStyle(color: context.palette.danger) : null,
      ),
    );
  }
}
