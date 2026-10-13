// 定时任务详情里的“助手记下的”（v2.13）：做法（第一次运行写下的步骤 / 来源）与观察（之后几次滚动改的经验），
// 每次运行开头助手都会读到（后端 app/task_brief.py）。这里只看和清空：点一行弹出全文（可选中复制），
// 底部“清空”= PATCH {runbook|note: ""}，下次运行就重新摸索 / 重新积累。改写交给助手（在对话里说就行），不在手机上编辑长文。
// 定时脚本不调助手，没有这一块；两项都没有时整块不出现。
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/resource.dart';
import '../../models/resources.dart';
import '../../theme/app_theme.dart';
import '../../theme/tokens.dart';
import '../../ui/kit.dart';
import '../../ui/motion.dart';
import '../../ui/sheets.dart';

/// 一项记下的东西：字段名（PATCH 用）、标题、说明、图标。
typedef _Memo = ({String field, String title, String hint, IconData icon, String text});

List<_Memo> _taskMemos(ScheduledTask t) => [
      if (t.runbook != null)
        (field: 'runbook', title: '做法', hint: '第一次运行时写下的步骤和来源，之后照着做', icon: Icons.menu_book_outlined, text: t.runbook!),
      if (t.note != null)
        (field: 'note', title: '观察', hint: '几次运行之间记下的经验', icon: Icons.lightbulb_outline_rounded, text: t.note!),
    ];

class TaskMemorySection extends ConsumerWidget {
  const TaskMemorySection({super.key, required this.task});
  final ScheduledTask task;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final memos = task.isScript ? const <_Memo>[] : _taskMemos(task);
    // 第一次运行写下做法时平滑长出来；清空后平滑收起
    return FadeSwitcher(
      alignment: AlignmentDirectional.topStart,
      child: memos.isEmpty
          ? const SizedBox(width: double.infinity, key: ValueKey('no-memo'))
          : Column(
              key: const ValueKey('memo'),
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                const SectionTitle('助手记下的'),
                ListGroup(children: [
                  for (final (i, m) in memos.indexed)
                    FadeSlideIn(key: ValueKey(m.field), delay: Motion.stagger(i), child: _MemoRow(task: task, memo: m)),
                ]),
              ],
            ),
    );
  }
}

class _MemoRow extends ConsumerWidget {
  const _MemoRow({required this.task, required this.memo});
  final ScheduledTask task;
  final _Memo memo;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final p = context.palette;
    final preview = memo.text.split('\n').where((l) => l.trim().isNotEmpty).take(2).join('\n');
    return Semantics(
      container: true,
      button: true,
      label: '${memo.title}：$preview，点按看全文',
      excludeSemantics: true,
      child: InkWell(
        borderRadius: BorderRadius.circular(Radii.md),
        onTap: () => _open(context, ref),
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: Sp.x4, vertical: Sp.x3),
          child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            SizedBox(width: Sp.x6, height: Sp.x6, child: Center(child: Icon(memo.icon, size: Sp.x5, color: p.text2))),
            const SizedBox(width: Sp.x3),
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text(memo.title, style: context.text.titleMedium),
                Text(preview, style: context.text.bodySmall, maxLines: 2, overflow: TextOverflow.ellipsis),
              ]),
            ),
            Padding(padding: const EdgeInsets.only(top: Sp.x1), child: Icon(Icons.chevron_right_rounded, color: p.text3)),
          ]),
        ),
      ),
    );
  }

  Future<void> _open(BuildContext context, WidgetRef ref) async {
    final clear = await showAppScrollSheet<bool>(context, builder: (ctx) => _MemoSheet(memo: memo));
    if (clear != true || !context.mounted) return;
    if (!await confirmDanger(context, title: '清空${memo.title}？', text: '下次运行时助手会重新摸索、重新记。', action: '清空')) return;
    try {
      await ref.read(tasksProvider.notifier).patch(task.id, {memo.field: ''});
      if (context.mounted) showToast(context, '已清空${memo.title}');
    } catch (e) {
      if (context.mounted) showToast(context, '没清空：$e');
    }
  }
}

class _MemoSheet extends StatelessWidget {
  const _MemoSheet({required this.memo});
  final _Memo memo;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    return Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      Padding(
        padding: const EdgeInsets.fromLTRB(Sp.x5, Sp.x2, Sp.x3, Sp.x3),
        child: Row(children: [
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(memo.title, style: context.text.titleMedium),
              Text(memo.hint, style: context.text.bodySmall),
            ]),
          ),
          CopyAction(text: memo.text, tooltip: '复制'),
        ]),
      ),
      SheetList(padding: const EdgeInsets.fromLTRB(Sp.x5, 0, Sp.x5, Sp.x3), children: [
        SelectableText(memo.text, style: context.text.bodyMedium?.copyWith(color: p.text2, height: 1.5)),
      ]),
      Padding(
        padding: const EdgeInsets.fromLTRB(Sp.x5, 0, Sp.x5, Sp.x4),
        child: Align(
          alignment: Alignment.centerRight,
          child: TextButton.icon(
            style: TextButton.styleFrom(foregroundColor: p.danger, minimumSize: const Size(0, A11y.minTap)),
            onPressed: () => Navigator.of(context).pop(true),
            icon: const Icon(Icons.delete_outline_rounded, size: 18),
            label: const Text('清空'),
          ),
        ),
      ),
    ]);
  }
}
