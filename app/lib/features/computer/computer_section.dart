// 我的电脑的状态部件（v1.25 起；v3.5.1 拆开，供“我的电脑”一屏概览和子页组合，见 computer_screen.dart）：
//   ComputerStatusGroup  状态卡：[▣] 运行中 / 行尾小字（2 个服务运行中）/ CPU · 内存 · 文件 / 内存条（吃紧变警示色）/ 打满警示 + “整台服务器”一行
//   ComputerJobsGroup    常驻服务 + 后台任务行（v1.82 服务排前面：健康点、副标题“运行 3 小时 · 端口 8000”、行尾 重启 / 立即重启 / 重新启动，
//                        POST /api/jobs/{id}/restart 不用确认）；任务行尾“取消”；点行看完整日志（job_block.dart 的 showJobLog）。
//                        [limit] 给了只露前几行，标题行尾“全部 N 个 ›”进子页。
//   ComputerRestartButton 标题行右侧的玻璃圆钮“重启”（只在运行中给）：确认后停掉后台任务、删容器，文件和装过的包都在（服务器 app/computer.py）。
//   ComputerPoll         静默轮询：有普通后台任务 → Timing.computerPoll（5 s）；只有常驻服务 → Timing.computerPollIdle（10 s）；
//                        [pollAlways] 且运行中（看进程 / CPU）→ 5 s；看不见（被盖住、切后台）时不问。
// 轮询精细化（v3.5.1）：每个部件 / 每一行用 ref.watch(provider.select(...)) 只听自己显示的那几个值，一次轮询只重建真变了的行。
// 数据只在 computerProvider(工作区 id)；文案规则在 models/computer.dart。
import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../blocks/job_block.dart';
import '../../core/api.dart';
import '../../core/swr.dart';
import '../../models/computer.dart';
import '../../models/job.dart';
import '../../theme/app_theme.dart';
import '../../theme/tokens.dart';
import '../../ui/glass.dart';
import '../../ui/kit.dart';
import '../../ui/motion.dart';
import '../../ui/sheets.dart';

/// 加载 / 静默刷新（轮询偶尔没连上不把整块换成错误）规则在 core/swr.dart；这里只管操作。
class ComputerNotifier extends SwrNotifier<ComputerStatus> {
  ComputerNotifier(this.ws);
  final String ws;

  @override
  String get path => '/api/projects/$ws/computer';
  String get _path => path;
  Api get _api => ref.read(apiProvider);

  @override
  ComputerStatus parse(Object? j) => ComputerStatus.fromJson(jsonMap(j));

  /// 重启：出错抛给调用方提示，旧状态不动。
  Future<void> restart() async => emit(await _api.post('$_path/restart'));

  /// 一键清理：返回腾出的字节，状态换成清理后的。
  Future<int> cleanup() async {
    final j = (await _api.post('$_path/cleanup') as Map).cast<String, dynamic>();
    emit(j['status']);
    return (j['freed'] as num?)?.toInt() ?? 0;
  }

  /// 端口预览：签一条带期限的链接（POST …/computer/preview），返回网址。服务没在听 / 只听本机 → ApiError（409，原因写好了）。
  Future<String> preview(int port) async {
    final j = (await _api.post('$_path/preview', {'port': port}) as Map).cast<String, dynamic>();
    return j['url'] as String? ?? '';
  }

  Future<void> cancelJob(String id) async {
    await _api.post('/api/jobs/$id/cancel');
    await reload();
  }

  /// 常驻服务手动重启（在跑 → 杀了重起；等重启 → 马上起；停了 → 重新拉起）。不行 → ApiError（409，原因写好了）。
  Future<void> restartService(String id) async {
    await _api.post('/api/jobs/$id/restart');
    await reload();
  }
}

final computerProvider =
    AsyncNotifierProvider.autoDispose.family<ComputerNotifier, ComputerStatus, String>(ComputerNotifier.new);

/// 静默轮询（看规则见文件头）。包在页面外层，自己不监听状态（不因轮询重建）。
class ComputerPoll extends ConsumerStatefulWidget {
  const ComputerPoll({super.key, required this.ws, required this.child, this.pollAlways = false});
  final String ws;
  final Widget child;

  /// 运行中就一直刷新（详情页看进程/CPU），不只在有后台任务 / 服务时。
  final bool pollAlways;

  @override
  ConsumerState<ComputerPoll> createState() => _ComputerPollState();
}

class _ComputerPollState extends ConsumerState<ComputerPoll> {
  Timer? _poll;
  DateTime _last = DateTime.now();

  @override
  void initState() {
    super.initState();
    _poll = Timer.periodic(Timing.computerPoll, (_) => _tick());
  }

  @override
  void dispose() {
    _poll?.cancel();
    super.dispose();
  }

  /// 这次该隔多久问一次；null = 不用问。
  Duration? _every(ComputerStatus s) {
    if (s.jobs.isNotEmpty) return Timing.computerPoll;
    if (s.liveServices > 0) return Timing.computerPollIdle;
    if (widget.pollAlways && s.running) return Timing.computerPoll;
    return null;
  }

  void _tick() {
    if (!mounted || !TickerMode.valuesOf(context).enabled) return;
    final s = ref.read(computerProvider(widget.ws)).value;
    final every = s == null ? null : _every(s);
    if (every == null) return;
    final now = DateTime.now();
    if (now.difference(_last) < every - const Duration(milliseconds: 500)) return; // 5 s 一拍，慢档隔一拍问一次
    _last = now;
    ref.read(computerProvider(widget.ws).notifier).reload().ignore();
  }

  @override
  Widget build(BuildContext context) => widget.child;
}

/// 标题行右侧的“重启”圆钮（只在运行中给；确认逻辑同 v1.25）。
class ComputerRestartButton extends ConsumerStatefulWidget {
  const ComputerRestartButton({super.key, required this.ws});
  final String ws;

  @override
  ConsumerState<ComputerRestartButton> createState() => _ComputerRestartButtonState();
}

class _ComputerRestartButtonState extends ConsumerState<ComputerRestartButton> {
  bool _restarting = false;

  Future<void> _restart() async {
    final s = ref.read(computerProvider(widget.ws)).value;
    if (s == null) return;
    if (!await confirmDanger(context, title: '重启这台电脑？', text: computerRestartText(s), action: '重启')) return;
    setState(() => _restarting = true);
    try {
      await ref.read(computerProvider(widget.ws).notifier).restart();
      if (mounted) showToast(context, '已重启，下次用到时自动开机');
    } on ApiError catch (e) {
      if (mounted) showToast(context, e.isNetwork ? '无法连接服务器，重启失败' : e.message);
    } finally {
      if (mounted) setState(() => _restarting = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final running = ref.watch(computerProvider(widget.ws).select((a) => a.value?.running ?? false));
    return FadeSwitcher(
      alignment: Alignment.centerRight,
      child: running
          ? GlassIconButton(
              key: const ValueKey('restart'),
              icon: Icons.restart_alt_rounded,
              tooltip: _restarting ? '正在重启' : '重启',
              onTap: _restarting ? null : _restart,
            )
          : const SizedBox.shrink(key: ValueKey('norestart')),
    );
  }
}

/// 状态卡显示的那几个值（record 按值比较：轮询回来没变就不重建）。
typedef _StatusView = ({
  String state,
  String detail,
  String? hint,
  bool hintWarn,
  double? ratio,
  String? oom,
  int oomKills,
  bool problem,
  bool running,
  String semantics,
});

_StatusView? _statusView(ComputerStatus? s) => s == null
    ? null
    : (
        state: s.state,
        detail: computerDetail(s),
        hint: computerHint(s),
        hintWarn: computerHintWarn(s),
        ratio: computerMemoryRatio(s),
        oom: computerOomNote(s),
        oomKills: s.oomKills,
        problem: !s.reachable,
        running: s.running,
        semantics: computerSemantics(s),
      );

/// 状态卡（v3.5.1 一屏概览）：一个分组里依次是 状态块（运行中、CPU、内存、磁盘、内存条、打满警示）→“整台服务器”一行
/// → 常驻服务 + 后台任务行（[limit] 给了只露前几行，再加一行“全部 N 个 ›”= [onAll]）。加载中 / 失败 → 不画。
/// [status] false = 只有服务 + 任务行（后台任务子页，见 [ComputerJobsGroup]）。
class ComputerStatusGroup extends ConsumerStatefulWidget {
  const ComputerStatusGroup({super.key, required this.ws, this.status = true, this.limit, this.onAll, this.delay = Duration.zero});
  final String ws;
  final bool status;
  final int? limit;
  final VoidCallback? onAll;
  final Duration delay;

  @override
  ConsumerState<ComputerStatusGroup> createState() => _ComputerStatusGroupState();
}

/// 后台任务子页：常驻服务 + 全部后台任务（不带状态块、不限行数）。
class ComputerJobsGroup extends StatelessWidget {
  const ComputerJobsGroup({super.key, required this.ws});
  final String ws;

  @override
  Widget build(BuildContext context) => ComputerStatusGroup(ws: ws, status: false);
}

class _ComputerStatusGroupState extends ConsumerState<ComputerStatusGroup> {
  final _cancelling = <String>{};
  final _bouncing = <String>{}; // 正在重启的服务

  ComputerNotifier get _ctl => ref.read(computerProvider(widget.ws).notifier);

  Future<void> _cancel(String id) async {
    setState(() => _cancelling.add(id));
    try {
      await _ctl.cancelJob(id);
    } on ApiError catch (e) {
      if (mounted) showToast(context, e.isNetwork ? '无法连接服务器，取消失败' : e.message);
    } finally {
      if (mounted) setState(() => _cancelling.remove(id));
    }
  }

  Future<void> _restartService(String id, String title) async {
    setState(() => _bouncing.add(id));
    try {
      await _ctl.restartService(id);
      if (mounted) showToast(context, '「$title」将在几秒内重新启动');
    } on ApiError catch (e) {
      if (mounted) showToast(context, e.isNetwork ? '无法连接服务器，重启失败' : e.message);
    } finally {
      if (mounted) setState(() => _bouncing.remove(id));
    }
  }

  @override
  Widget build(BuildContext context) {
    // 只听“加载了没有、有哪几行”（id 串）：行里的数字变了由各行自己重建
    final ids = ref.watch(computerProvider(widget.ws).select((a) {
      final s = a.value;
      if (s == null) return null;
      return [for (final v in s.services) 's:${v.job.id}', for (final j in s.jobs) 'j:${j.id}'].join('\n');
    }));
    final all = ids == null || ids.isEmpty ? const <String>[] : ids.split('\n');
    final shown = widget.limit == null ? all : all.take(widget.limit!).toList();
    final more = widget.limit != null && all.length > widget.limit!;
    final none = ids == null || (!widget.status && all.isEmpty);
    // “整台服务器”有没有这一行由这里定（空行也会被 ListGroup 画一条分隔线）
    final machine = widget.status &&
        ref.watch(computerProvider(widget.ws).select((a) => switch (a.value?.machine) { final m? => machineLine(m) != null, _ => false }));
    return FadeSwitcher(
      child: none
          ? const SizedBox.shrink(key: ValueKey('none'))
          : FadeSlideIn(
              key: const ValueKey('computer'),
              delay: widget.delay,
              child: ListGroup(children: [
                if (widget.status) _StatusTile(ws: widget.ws),
                if (machine) _MachineRow(ws: widget.ws),
                for (final k in shown)
                  if (k.startsWith('s:'))
                    _ServiceRow(
                      key: ValueKey('svc-${k.substring(2)}'),
                      ws: widget.ws,
                      id: k.substring(2),
                      busy: _bouncing.contains(k.substring(2)),
                      onRestart: _restartService,
                    )
                  else
                    _JobRow(
                      key: ValueKey('job-${k.substring(2)}'),
                      ws: widget.ws,
                      id: k.substring(2),
                      cancelling: _cancelling.contains(k.substring(2)),
                      onCancel: _cancel,
                    ),
                if (more)
                  ListRow(
                    key: const Key('computer-all-tasks'),
                    leading: const SizedBox.square(dimension: Layout.rowIcon),
                    title: '全部 ${all.length} 个 ›',
                    titleWidget: Text('全部 ${all.length} 个 ›', style: context.text.bodyMedium?.copyWith(color: context.palette.text2)),
                    onTap: widget.onAll,
                    trailing: const SizedBox.shrink(),
                  ),
              ]),
            ),
    );
  }
}

class _MachineRow extends ConsumerWidget {
  const _MachineRow({required this.ws});
  final String ws;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final line = ref.watch(computerProvider(ws).select((a) => switch (a.value?.machine) { final m? => machineLine(m), _ => null }));
    // v2.85 整台服务器（只有个人工作区给）
    return line == null ? const SizedBox.shrink() : ListRow(icon: Icons.dns_rounded, title: '整台服务器', subtitle: line);
  }
}

class _StatusTile extends ConsumerWidget {
  const _StatusTile({required this.ws});
  final String ws;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final v = ref.watch(computerProvider(ws).select((a) => _statusView(a.value)));
    if (v == null) return const SizedBox.shrink();
    final p = context.palette;
    final ratio = v.ratio, hint = v.hint, oom = v.oom, problem = v.problem;
    return Semantics(
      container: true,
      label: [v.semantics, ?oom].join('，'),
      excludeSemantics: true,
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: Sp.x4, vertical: Sp.x3 - 2), // 与 ListRow 同一条行首线、同一行高
        child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Icon(problem ? Icons.cloud_off_rounded : Icons.computer_rounded,
              size: Layout.rowIcon, color: problem ? p.warning : (v.running ? p.text2 : p.text3)),
          const SizedBox(width: Sp.x4),
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
              Row(children: [
                Expanded(
                  child: SwapSwitcher(
                    child: Text(computerStateLabel(v.state),
                        key: ValueKey(v.state),
                        style: context.text.titleMedium?.copyWith(color: problem ? p.warning : null)),
                  ),
                ),
                if (hint != null) SwapSwitcher(child: RowHint(hint, key: ValueKey(hint), warn: v.hintWarn)),
              ]),
              const SizedBox(height: Sp.x1),
              Text(v.detail, style: context.text.bodySmall, maxLines: 2, overflow: TextOverflow.ellipsis),
              RiseSwitcher(
                child: ratio == null
                    ? const SizedBox.shrink(key: ValueKey('nometer'))
                    : Padding(
                        key: const ValueKey('meter'),
                        padding: const EdgeInsets.only(top: Sp.x2),
                        child: MeterBar(
                            value: ratio, height: Sp.x1, color: ratio >= computerMemoryTight ? p.warning : p.text2),
                      ),
              ),
              RiseSwitcher(
                child: oom == null
                    ? const SizedBox.shrink(key: ValueKey('nooom'))
                    : Padding(
                        key: ValueKey('oom-${v.oomKills}'),
                        padding: const EdgeInsets.only(top: Sp.x2),
                        child: Text(oom, style: context.text.bodySmall?.copyWith(color: p.warning)),
                      ),
              ),
            ]),
          ),
        ]),
      ),
    );
  }
}

JobInfo? _jobOf(ComputerStatus? s, String id) {
  for (final j in s?.jobs ?? const <JobInfo>[]) {
    if (j.id == id) return j;
  }
  return null;
}

ServiceInfo? _serviceOf(ComputerStatus? s, String id) {
  for (final v in s?.services ?? const <ServiceInfo>[]) {
    if (v.job.id == id) return v;
  }
  return null;
}

class _JobRow extends ConsumerWidget {
  const _JobRow({super.key, required this.ws, required this.id, required this.cancelling, required this.onCancel});
  final String ws, id;
  final bool cancelling;
  final void Function(String id) onCancel;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final v = ref.watch(computerProvider(ws).select((a) => switch (_jobOf(a.value, id)) {
          final j? => (title: j.title, subtitle: jobRowSubtitle(j)),
          _ => null,
        }));
    if (v == null) return const SizedBox.shrink();
    final p = context.palette;
    return ListRow(
      leading: SizedBox.square(dimension: Layout.rowIcon, child: Center(child: PulseDot(color: p.accent, size: 8))),
      title: v.title,
      subtitle: v.subtitle,
      trailing: TextButton(onPressed: cancelling ? null : () => onCancel(id), child: Text(cancelling ? '正在取消' : '取消')),
      onTap: () {
        final j = _jobOf(ref.read(computerProvider(ws)).value, id);
        if (j != null) showJobLog(context, ref, j);
      },
    );
  }
}

/// 常驻服务一行（v1.82）。健康点：在跑 = 任务卡同款脉冲（JobStatusMark），等重启 = 警示色脉冲，停了 = 警示图标。
class _ServiceRow extends ConsumerWidget {
  const _ServiceRow({super.key, required this.ws, required this.id, required this.busy, required this.onRestart});
  final String ws, id;
  final bool busy;
  final void Function(String id, String title) onRestart;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final v = ref.watch(computerProvider(ws).select((a) => switch (_serviceOf(a.value, id)) {
          final x? => (title: x.job.title, health: x.health, line: serviceLine(x), semantics: serviceSemantics(x)),
          _ => null,
        }));
    if (v == null) return const SizedBox.shrink();
    final p = context.palette;
    final mark = switch (v.health) {
      ServiceHealth.up => const JobStatusMark(JobTone.running),
      ServiceHealth.restarting => PulseDot(color: p.warning, size: 8),
      ServiceHealth.gaveUp => const JobStatusMark(JobTone.problem),
    };
    return Semantics(
      label: v.semantics,
      child: ListRow(
        leading: SizedBox.square(
          dimension: Layout.rowIcon,
          child: Center(child: SwapSwitcher(child: KeyedSubtree(key: ValueKey(v.health), child: mark))),
        ),
        title: v.title,
        problem: v.health == ServiceHealth.gaveUp ? '已停止' : null,
        subtitle: v.line,
        trailing: TextButton(onPressed: busy ? null : () => onRestart(id, v.title), child: Text(busy ? '正在重启' : serviceAction(v.health))),
        onTap: () {
          final x = _serviceOf(ref.read(computerProvider(ws)).value, id);
          if (x != null) showJobLog(context, ref, x.job);
        },
      ),
    );
  }
}
