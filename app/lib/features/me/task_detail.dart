// 定时任务详情（/me/tasks/:id）：上面是任务本身（时间、去向 + 非默认的模型 / 思考档、提示词、开关、立即运行；标题栏“编辑”= task_form.dart 同一张表单），
// 时间下面一行是“下次运行”（服务端算好的 next_run_at，见 task_labels.dart）；
// 下面是最近的运行记录（GET /api/tasks/{id}/runs，新的在前）：成功 / 失败（带原因）/ 正在运行，
// 哪次、手动还是定时、用了多久；报告任务的那次可以点开对话（openConversation），面板任务没有对话。
// 数据流：任务本身读 tasksProvider（列表页同一份，开关/删除走它的 notifier）；记录是 taskRunsProvider(id)，
// autoDispose，离开页面就丢。有运行在排队（run_requested）或进行中时每 Timing.taskRunPoll 刷新两者，
// 都结束了就停——不在后台空转。Home 上的“任务失败 / 连续失败已暂停”提醒卡（target=tasks）直达这一页；
// 自动暂停时卡片里多一条说明（_PauseNote，文案 task_labels.dart autoPauseNote）。
import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/api.dart';
import '../../core/resource.dart';
import '../../models/resources.dart';
import '../../theme/app_theme.dart';
import '../../theme/tokens.dart';
import '../../ui/format.dart';
import '../../ui/glass_mode.dart';
import '../../ui/kit.dart';
import '../../ui/sub_page.dart';
import '../../ui/motion.dart';
import '../../ui/sheets.dart';
import '../chat/open_conversation.dart';
import 'task_form.dart';
import 'task_labels.dart';
import 'task_model_picker.dart';
import '../chat/model_choice.dart' show modelCatalogProvider;

final taskRunsProvider = FutureProvider.autoDispose.family<List<TaskRun>, String>((ref, id) async => [
      for (final j in (await ref.read(apiProvider).get('/api/tasks/$id/runs') as List)) TaskRun.fromJson((j as Map).cast<String, dynamic>()),
    ]);

/// 任务在忙：已点“立即运行”还没被领走，或有一条记录还在跑。
bool taskBusy(ScheduledTask task, List<TaskRun>? runs) => task.runRequested || (runs?.any((r) => r.running) ?? false);

class TaskDetailScreen extends ConsumerStatefulWidget {
  const TaskDetailScreen({super.key, required this.id});
  final String id;

  @override
  ConsumerState<TaskDetailScreen> createState() => _TaskDetailScreenState();
}

class _TaskDetailScreenState extends ConsumerState<TaskDetailScreen> {
  Timer? _poll;

  Future<void> _refresh() async {
    ref.invalidate(taskRunsProvider(widget.id));
    try {
      await ref.read(tasksProvider.notifier).reload();
    } catch (_) {} // 断网时保留旧值，下次再问
  }

  void _syncPoll(bool busy) {
    if (busy && _poll == null) {
      _poll = Timer.periodic(Timing.taskRunPoll, (_) => _refresh());
    } else if (!busy && _poll != null) {
      _poll!.cancel();
      _poll = null;
    }
  }

  @override
  void dispose() {
    _poll?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final tasks = ref.watch(tasksProvider);
    final task = tasks.value?.where((t) => t.id == widget.id).firstOrNull;
    if (task == null) {
      _syncPoll(false);
      return SubPage(
        title: const Text('定时任务'),
        body: tasks.isLoading
            ? const PageBody(children: [SkeletonList(rows: 3)])
            : const PageBody(children: [EmptyHint(icon: Icons.event_busy_rounded, title: '这个任务已经不在了', text: '可能已在别的设备上删除。')]),
      );
    }
    final runs = ref.watch(taskRunsProvider(widget.id));
    _syncPoll(taskBusy(task, runs.value));
    return SubPage(
      title: Text(task.name),
      actions: [
        IconButton(tooltip: '编辑', icon: const Icon(Icons.edit_outlined), onPressed: () => _edit(task)),
        IconButton(tooltip: '删除任务', icon: const Icon(Icons.delete_outline_rounded), onPressed: () => _delete(task)),
      ],
      body: PullRefresh(
        onRefresh: _refresh,
        child: PageBody(children: [
          FadeSlideIn(child: _Header(task: task, busy: taskBusy(task, runs.value), onRun: () => _runNow(task))),
          const SectionTitle('运行记录'),
          runs.when(
            skipLoadingOnReload: true,
            loading: () => const SkeletonList(rows: 3),
            error: (e, _) => EmptyHint(
              icon: Icons.cloud_off_rounded,
              title: '运行记录加载失败',
              text: '$e',
              action: OutlinedButton(onPressed: () => ref.invalidate(taskRunsProvider(widget.id)), child: const Text('重试')),
            ),
            data: (list) => list.isEmpty && !task.runRequested
                ? const EmptyHint(icon: Icons.history_rounded, title: '还没运行过', text: '到点会自动运行，也可以点上面的“立即运行”试一次。')
                : ListGroup(children: [
                    if (task.runRequested && !list.any((r) => r.running)) const _QueuedRow(),
                    for (final (i, r) in list.indexed)
                      FadeSlideIn(key: ValueKey(r.id), delay: Motion.stagger(i), child: TaskRunRow(run: r, panel: task.isPanel)),
                  ]),
          ),
        ]),
      ),
    );
  }

  Future<void> _runNow(ScheduledTask task) async {
    try {
      await ref.read(apiProvider).post('/api/tasks/${task.id}/run');
      await _refresh();
      if (mounted) showToast(context, task.isPanel ? '已开始，面板稍后更新' : '已开始，结果会出现在 Home');
    } catch (e) {
      if (mounted) showToast(context, '没能开始：$e');
    }
  }

  /// 改名称/指令/计划（也可在重复/一次之间切换）。一次性任务改到以后 = 已完成的重新排上。
  Future<void> _edit(ScheduledTask task) async {
    final changes = await showTaskForm(context, task: task);
    if (changes == null || changes.isEmpty) return;
    try {
      await ref.read(tasksProvider.notifier).patch(task.id, changes);
    } catch (e) {
      if (mounted) showToast(context, '没改成：$e');
    }
  }

  Future<void> _delete(ScheduledTask task) async {
    if (!await confirmDanger(context, title: '删除「${task.name}」？', text: '运行记录和它在 Home 上的卡片会一起删除。')) return;
    await ref.read(tasksProvider.notifier).remove(task.id);
    if (mounted) context.pop();
  }
}

class _Header extends ConsumerWidget {
  const _Header({required this.task, required this.busy, required this.onRun});
  final ScheduledTask task;
  final bool busy;
  final VoidCallback onRun;

  /// 选了非默认的模型 / 思考档才写（“深度 · 思考 高”），默认不占字。
  static String? _model(ScheduledTask t, WidgetRef ref) {
    final s = taskModelLabel(t, ref.watch(modelCatalogProvider).value);
    return s.isEmpty ? null : s;
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final p = context.palette;
    return AppCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          IconBadge(taskIcon(task)),
          const SizedBox(width: Sp.x3),
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(scheduleLabel(task), style: context.text.titleMedium),
              Text(
                [task.isPanel ? '刷新 Home 上的面板' : '结果放进 Home 收件箱', ?_model(task, ref)].join(' · '),
                style: context.text.bodySmall,
              ),
              // 下次运行跟着开关/改时间变：SwapSwitcher 让文字换得不突兀
              if (nextRunLabel(task).isNotEmpty)
                SwapSwitcher(
                  child: Text(nextRunLabel(task), key: ValueKey(nextRunLabel(task)), style: context.text.bodySmall?.copyWith(color: p.text2)),
                ),
            ]),
          ),
          Switch(
            value: task.active,
            onChanged: (v) => ref.read(tasksProvider.notifier).patch(task.id, {'active': v}),
          ),
        ]),
        // 自动暂停的说明条：恢复（开关 / 试跑成功）后平滑收起
        FadeSwitcher(
          alignment: AlignmentDirectional.topStart,
          child: autoPauseNote(task) == null
              ? const SizedBox(width: double.infinity, key: ValueKey('no-note'))
              : Padding(
                  key: const ValueKey('paused-note'),
                  padding: const EdgeInsets.only(top: Sp.x3),
                  child: _PauseNote(text: autoPauseNote(task)!),
                ),
        ),
        const SizedBox(height: Sp.x3),
        Text(task.prompt, style: context.text.bodyMedium?.copyWith(color: p.text2)),
        const SizedBox(height: Sp.x3),
        Align(
          alignment: Alignment.centerRight,
          child: FilledButton.icon(
            style: FilledButton.styleFrom(minimumSize: const Size(0, A11y.minTap)),
            onPressed: busy ? null : onRun,
            icon: Icon(busy ? Icons.hourglass_top_rounded : Icons.play_arrow_rounded, size: 18),
            label: SwapSwitcher(child: Text(busy ? '运行中…' : '立即运行', key: ValueKey(busy))),
          ),
        ),
      ]),
    );
  }
}

/// 连续失败被自动暂停时的一条说明：小块底色 + 警示色图标，文字保持正文色（不让整块变黄）。
class _PauseNote extends StatelessWidget {
  const _PauseNote({required this.text});
  final String text;

  @override
  Widget build(BuildContext context) => Container(
        width: double.infinity,
        padding: const EdgeInsets.all(Sp.x3),
        decoration: BoxDecoration(color: context.tileFill, borderRadius: BorderRadius.circular(Radii.tile)),
        child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Icon(Icons.pause_circle_outline_rounded, size: Sp.x5, color: context.palette.warning),
          const SizedBox(width: Sp.x2),
          Expanded(child: Text(text, style: context.text.bodySmall?.copyWith(color: context.palette.text))),
        ]),
      );
}

/// 已点“立即运行”、worker 还没领走（≤15 秒）：一行占位，免得用户以为没点上。
class _QueuedRow extends StatelessWidget {
  const _QueuedRow();

  @override
  Widget build(BuildContext context) => _RunLayout(
        status: PulseDot(color: context.palette.text3),
        title: '排队中',
        subtitle: '马上开始',
        semantics: '排队中，马上开始',
      );
}

/// 一次运行：状态 · 什么时候 · 手动/定时 · 用时；失败的在下面写原因；有对话的可点开。
class TaskRunRow extends ConsumerWidget {
  const TaskRunRow({super.key, required this.run, required this.panel});
  final TaskRun run;
  final bool panel;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final p = context.palette;
    final (Widget icon, String label) = run.running
        ? (PulseDot(color: p.accent), '正在运行')
        : run.failed
            ? (Icon(Icons.error_rounded, color: p.danger, size: Sp.x5), '失败')
            : (Icon(Icons.check_circle_outline_rounded, color: p.text2, size: Sp.x5), '成功');
    final when = formatWhen(run.startedAt);
    final how = run.manual ? '手动' : '定时';
    final took = run.running ? '进行中' : (run.durationMs == null ? '' : '用时 ${formatDuration(run.durationMs!)}');
    final subtitle = [how, if (took.isNotEmpty) took].join(' · ');
    final conv = run.conversationId;
    return _RunLayout(
      status: icon,
      title: when,
      subtitle: subtitle,
      error: run.failed ? run.error : null,
      semantics: '$label，$when，$subtitle${run.failed && run.error != null ? '，原因：${run.error}' : ''}${conv != null ? '，点按打开报告' : ''}',
      onTap: conv == null ? null : () => openConversation(context, ref, conv),
    );
  }
}

class _RunLayout extends StatelessWidget {
  const _RunLayout({required this.status, required this.title, required this.subtitle, required this.semantics, this.error, this.onTap});
  final Widget status;
  final String title, subtitle, semantics;
  final String? error;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final row = Padding(
      padding: const EdgeInsets.symmetric(horizontal: Sp.x4, vertical: Sp.x3),
      child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
        SizedBox(width: Sp.x6, height: Sp.x6, child: Center(child: status)),
        const SizedBox(width: Sp.x3),
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(title, style: context.text.titleMedium),
            Text(subtitle, style: context.text.bodySmall),
            if (error != null) ...[
              const SizedBox(height: Sp.x1),
              Text(error!, style: context.text.bodySmall?.copyWith(color: p.danger), maxLines: 4, overflow: TextOverflow.ellipsis),
            ],
          ]),
        ),
        if (onTap != null) Padding(padding: const EdgeInsets.only(top: Sp.x1), child: Icon(Icons.chevron_right_rounded, color: p.text3)),
      ]),
    );
    return Semantics(
      container: true,
      button: onTap != null,
      label: semantics,
      excludeSemantics: true,
      child: onTap == null ? row : InkWell(onTap: onTap, borderRadius: BorderRadius.circular(Radii.md), child: row),
    );
  }
}
