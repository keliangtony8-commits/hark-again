// 定时任务列表（面板也是任务，这里统一管理）。版式（v0.77，与技能页同一套）：
// 页头 = 摘要小标签（数字变化时换一下）+ “下一个：早间简报 · 明天 08:00”；
// 分组：需要留意（上次失败 / 连续失败被自动暂停）/ 在跑 / Home 面板 / 已停下（暂停或一次性已完成，变淡）；分组规则在 task_library.dart；
// 行错峰入场，左滑删除（先确认），行尾开关；空列表给起步模板（点了带内容打开新建表单）。
// 点一行进详情（task_detail.dart：运行记录、立即运行、编辑、删除）。
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/resource.dart';
import '../../models/resources.dart';
import '../../theme/app_theme.dart';
import '../../theme/tokens.dart';
import '../../ui/glass.dart';
import '../../ui/kit.dart';
import '../../ui/motion.dart';
import '../../ui/sheets.dart';
import '../../ui/sub_page.dart';
import 'task_form.dart';
import 'task_labels.dart';
import 'task_library.dart';

/// 新建任务（可带起步模板）：列表页 FAB 和空态模板共用。
Future<void> createTask(BuildContext context, WidgetRef ref, {TaskStarter? starter}) async {
  final body = await showTaskForm(context, starter: starter);
  if (body != null) await ref.read(tasksProvider.notifier).create(body);
}

class TasksScreen extends ConsumerWidget {
  const TasksScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final tasks = ref.watch(tasksProvider);
    return SubPage(
      title: const Text('定时任务'),
      floatingActionButton: FloatingActionButton(
        tooltip: '新定时任务',
        onPressed: () => createTask(context, ref),
        child: const Icon(Icons.add_rounded),
      ),
      body: AsyncBody<ScheduledTask>(
        value: tasks,
        onRetry: () => ref.invalidate(tasksProvider),
        builder: (list) {
          final g = groupTasks(list);
          var i = 0; // 整页错峰序号：页头之后一行一行进
          Widget rows(List<ScheduledTask> items) =>
              ListGroup(children: [for (final t in items) _TaskRow(task: t, delay: Motion.stagger(i++, from: 1))]);
          return PullRefresh(
            onRefresh: () => ref.read(tasksProvider.notifier).reload(),
            child: PageBody(children: [
              PageIntro(summary: taskSummary(list), line: _nextLine(nextUp(list))),
              if (list.isEmpty) const _Starters(),
              if (g.attention.isNotEmpty) ...[SectionTitle('需要留意', count: g.attention.length), rows(g.attention)],
              if (g.running.isNotEmpty) ...[SectionTitle('在跑', count: g.running.length), rows(g.running)],
              if (g.panels.isNotEmpty) ...[SectionTitle('Home 面板', count: g.panels.length), rows(g.panels)],
              if (g.idle.isNotEmpty) ...[SectionTitle('已停下', count: g.idle.length), rows(g.idle)],
            ]),
          );
        },
      ),
    );
  }
}

/// 页头第二行：下一个要跑的；没有就是一句说明。
String _nextLine((String, String)? next) =>
    next == null ? '到点我会自己去做，做完把结果发给你；面板按计划刷新。' : '下一个：${next.$1} · ${next.$2}';

/// 空列表：起步模板（点了带内容打开新建表单，没点“创建”前什么都不会存）。
class _Starters extends ConsumerWidget {
  const _Starters();

  @override
  Widget build(BuildContext context, WidgetRef ref) => Padding(
        padding: const EdgeInsets.only(top: Sp.x4),
        child: StarterCard(
          title: '还没有定时任务',
          text: '在这里建，或在聊天里说“每天早上 8 点给我今天的天气和日程”。也可以从一个开始改：',
          starters: [
            for (final st in taskStarters)
              PillButton(label: st.name, icon: Icons.add_rounded, onTap: () => createTask(context, ref, starter: st)),
          ],
        ),
      );
}

class _TaskRow extends ConsumerWidget {
  const _TaskRow({required this.task, this.delay = Duration.zero});
  final ScheduledTask task;
  final Duration delay;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final state = taskStateLabel(task);
    final parts = [scheduleLabel(task), if (state.isNotEmpty) state];
    final idle = taskIdle(task);
    return SwipeToDelete(
      id: task.id,
      // 与详情页删除同一句（运行记录、Home 卡片由服务端 task_store.remove 连带删除）
      confirm: () => confirmDanger(context, title: '删除「${task.name}」？', text: '运行记录和它在 Home 上的卡片会一起删除。'),
      onDelete: () => ref.read(tasksProvider.notifier).remove(task.id),
      child: FadeSlideIn(
        delay: delay,
        child: Dimmed(
          dimmed: idle,
          child: RowTile(
            leading: _TaskBadge(task: task),
            title: task.name,
            // 自动暂停 = 这一行的问题：只把问题那几个字染警示色（RowTile.problem），计划照常
            problem: task.autoPaused ? state : null,
            subtitle: task.autoPaused ? scheduleLabel(task) : parts.join(' · '),
            onTap: () => context.push('/me/tasks/${task.id}'),
            trailing: Semantics(
              label: '启用「${task.name}」',
              child: Switch(value: task.active, onChanged: (v) => ref.read(tasksProvider.notifier).patch(task.id, {'active': v})),
            ),
          ),
        ),
      ),
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
