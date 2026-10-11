// 定时任务列表：开关、新建（重复/一次，schedule_picker.dart）；点一行进详情（task_detail.dart：运行记录、立即运行、删除）。
// 上一次运行失败的任务在图标上挂一个红点、副标题写“上次失败”。面板也是任务，这里统一管理。
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/resource.dart';
import '../../models/resources.dart';
import '../../theme/app_theme.dart';
import '../../ui/kit.dart';
import '../../ui/sub_page.dart';
import '../../ui/motion.dart';
import 'task_form.dart';
import 'task_labels.dart';

class TasksScreen extends ConsumerWidget {
  const TasksScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final tasks = ref.watch(tasksProvider);
    return SubPage(
      title: const Text('定时任务'),
      floatingActionButton: FloatingActionButton(onPressed: () => _create(context, ref), child: const Icon(Icons.add_rounded)),
      body: AsyncBody<ScheduledTask>(
        value: tasks,
        onRetry: () => ref.invalidate(tasksProvider),
        empty: const EmptyHint(icon: Icons.schedule_rounded, title: '还没有定时任务', text: '比如“每天早上 8 点给我今天的天气和日程”。'),
        builder: (list) => PageBody(children: [
          ListGroup(children: [for (final t in list) _TaskRow(task: t)]),
        ]),
      ),
    );
  }

  Future<void> _create(BuildContext context, WidgetRef ref) async {
    final body = await showTaskForm(context);
    if (body != null) await ref.read(tasksProvider.notifier).create(body);
  }

}

class _TaskRow extends ConsumerWidget {
  const _TaskRow({required this.task});
  final ScheduledTask task;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final state = taskStateLabel(task);
    final parts = [
      if (task.isPanel) 'Home 面板',
      scheduleLabel(task),
      if (state.isNotEmpty) state,
    ];
    return RowTile(
      leading: _TaskBadge(task: task),
      title: task.name,
      subtitle: parts.join(' · '),
      onTap: () => context.push('/me/tasks/${task.id}'),
      trailing: Switch(value: task.active, onChanged: (v) => ref.read(tasksProvider.notifier).patch(task.id, {'active': v})),
    );
  }
}

/// 行首图标；上次失败时右上角一个红点。
class _TaskBadge extends StatelessWidget {
  const _TaskBadge({required this.task});
  final ScheduledTask task;

  @override
  Widget build(BuildContext context) => DotBadge(
        visible: task.lastFailed,
        color: context.palette.danger,
        label: '上次运行失败',
        child: IconBadge(taskIcon(task)),
      );
}
