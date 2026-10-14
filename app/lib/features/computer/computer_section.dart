// “电脑”一节（v1.25）：工作区背后那台云端 Linux 现在怎样——项目首屏和“我的 → 我的电脑”共用这一块。
//   [▣] 运行中                               2 个任务运行中
//       内存 312 MB / 1 GB · 文件 120 MB
//       ▬▬▬▬▬▬▬▭▭▭▭▭  （内存条，吃紧变警示色）
//   ─────────────────────────────────────
//   [●] 训练模型                                  取消
//       运行 3 分 05 秒 · $ python train.py
// 标题行右边“重启”（只在运行中给）：确认后停掉后台任务、删容器，文件和装过的包都在（服务器 app/computer.py）。
// 有后台任务在跑时每 Timing.computerPoll 静默刷新一次（看不见时不问）；点任务行看完整日志（job_block.dart 的 showJobLog）。
// 数据只在 computerProvider(工作区 id)；文案规则在 models/computer.dart。
// v1.27：说明行带 CPU；内存打满被系统杀过程序 → 状态块里一行警示；[onOpen] 给了（项目首屏）→ 状态块可点、进电脑详情页；
// [pollAlways]（详情页）→ 运行中就一直刷新（看进程、CPU），不只在有后台任务时。
// v1.82 常驻服务排在任务前面（后端 app/services.py）：健康点（在跑脉冲 / 等重启警示脉冲 / 停了警示图标）、
//   副标题“运行 3 小时 · 端口 8000 · 已重启 2 次”，行尾 重启 / 立即重启 / 重新启动（POST /api/jobs/{id}/restart，不用确认：
//   不丢文件，日志接着写）；点行看完整日志。停了的服务留 24 小时，行尾小字“1 个服务停了”变警示色。
import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../blocks/job_block.dart';
import '../../core/api.dart';
import '../../models/computer.dart';
import '../../models/job.dart';
import '../../theme/app_theme.dart';
import '../../theme/tokens.dart';
import '../../ui/glass.dart';
import '../../ui/kit.dart';
import '../../ui/motion.dart';
import '../../ui/sheets.dart';

class ComputerNotifier extends AsyncNotifier<ComputerStatus> {
  ComputerNotifier(this.ws);
  final String ws;

  String get _path => '/api/projects/$ws/computer';
  Api get _api => ref.read(apiProvider);

  @override
  Future<ComputerStatus> build() async => _parse(await _api.get(_path));

  ComputerStatus _parse(dynamic j) => ComputerStatus.fromJson((j as Map).cast<String, dynamic>());

  /// 静默刷新：失败保留旧数据（轮询偶尔没连上不该把整块换成错误）。
  Future<void> reload() async {
    try {
      state = AsyncData(_parse(await _api.get(_path)));
    } on ApiError {
      if (!state.hasValue) rethrow;
    }
  }

  /// 重启：出错抛给调用方提示，旧状态不动。
  Future<void> restart() async => state = AsyncData(_parse(await _api.post('$_path/restart')));

  /// 一键清理：返回腾出的字节，状态换成清理后的。
  Future<int> cleanup() async {
    final j = (await _api.post('$_path/cleanup') as Map).cast<String, dynamic>();
    state = AsyncData(_parse(j['status']));
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

class ComputerSection extends ConsumerStatefulWidget {
  const ComputerSection(
      {super.key, required this.ws, this.title = '电脑', this.delay = Duration.zero, this.onOpen, this.pollAlways = false});
  final String ws;
  final String title;

  /// 点状态块去哪（项目首屏 → 这台电脑的详情页）；null = 状态块不可点。
  final VoidCallback? onOpen;

  /// 运行中就一直按 Timing.computerPoll 刷新（详情页看进程/CPU）；否则只在有后台任务时刷新。
  final bool pollAlways;

  /// 入场错峰（首屏里排在别的节后面）。
  final Duration delay;

  @override
  ConsumerState<ComputerSection> createState() => _ComputerSectionState();
}

class _ComputerSectionState extends ConsumerState<ComputerSection> {
  Timer? _poll;
  bool _restarting = false;
  final _cancelling = <String>{};
  final _bouncing = <String>{}; // 正在重启的服务

  ComputerNotifier get _ctl => ref.read(computerProvider(widget.ws).notifier);

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

  void _tick() {
    if (!mounted || !TickerMode.valuesOf(context).enabled) return;
    final s = ref.read(computerProvider(widget.ws)).value;
    if (s != null && (s.busy || (widget.pollAlways && s.running))) _ctl.reload().ignore();
  }

  Future<void> _restart(ComputerStatus s) async {
    if (!await confirmDanger(context, title: '重启这台电脑？', text: computerRestartText(s), action: '重启')) return;
    setState(() => _restarting = true);
    try {
      await _ctl.restart();
      if (mounted) showToast(context, '已重启，下次用到时自动开机');
    } on ApiError catch (e) {
      if (mounted) showToast(context, e.isNetwork ? '无法连接服务器，重启失败' : e.message);
    } finally {
      if (mounted) setState(() => _restarting = false);
    }
  }

  Future<void> _cancel(JobInfo j) async {
    setState(() => _cancelling.add(j.id));
    try {
      await _ctl.cancelJob(j.id);
    } on ApiError catch (e) {
      if (mounted) showToast(context, e.isNetwork ? '无法连接服务器，取消失败' : e.message);
    } finally {
      if (mounted) setState(() => _cancelling.remove(j.id));
    }
  }

  Future<void> _restartService(ServiceInfo v) async {
    setState(() => _bouncing.add(v.job.id));
    try {
      await _ctl.restartService(v.job.id);
      if (mounted) showToast(context, '「${v.job.title}」将在几秒内重新启动');
    } on ApiError catch (e) {
      if (mounted) showToast(context, e.isNetwork ? '无法连接服务器，重启失败' : e.message);
    } finally {
      if (mounted) setState(() => _bouncing.remove(v.job.id));
    }
  }

  @override
  Widget build(BuildContext context) {
    final s = ref.watch(computerProvider(widget.ws)).value; // 加载中 / 失败 → 不画这一节（和“文件”一样）
    return FadeSwitcher(
      child: s == null
          ? const SizedBox.shrink(key: ValueKey('none'))
          : FadeSlideIn(
              key: const ValueKey('computer'),
              delay: widget.delay,
              child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                SectionTitle(widget.title,
                    trailing: s.running
                        ? TextButton(onPressed: _restarting ? null : () => _restart(s), child: Text(_restarting ? '正在重启' : '重启'))
                        : null),
                GlassGroup(children: [
                  _StatusTile(s, onOpen: widget.onOpen),
                  if (s.machine != null && machineLine(s.machine!) != null) // v2.85 整台服务器（只有个人工作区给）
                    RowTile(icon: Icons.dns_rounded, title: '整台服务器', subtitle: machineLine(s.machine!)),
                  for (final v in s.services)
                    _ServiceRow(
                      key: ValueKey('svc-${v.job.id}'),
                      service: v,
                      busy: _bouncing.contains(v.job.id),
                      onRestart: () => _restartService(v),
                    ),
                  for (final j in s.jobs)
                    _JobRow(
                      key: ValueKey('job-${j.id}'),
                      job: j,
                      cancelling: _cancelling.contains(j.id),
                      onCancel: () => _cancel(j),
                    ),
                ]),
              ]),
            ),
    );
  }
}

class _StatusTile extends StatelessWidget {
  const _StatusTile(this.s, {this.onOpen});
  final ComputerStatus s;
  final VoidCallback? onOpen;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final ratio = computerMemoryRatio(s);
    final hint = computerHint(s);
    final problem = !s.reachable;
    final oom = computerOomNote(s);
    final tile = Semantics(
      container: true,
      button: onOpen != null,
      label: [computerSemantics(s), ?oom].join('，'),
      excludeSemantics: true,
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: Sp.x4, vertical: Sp.x3 - 2), // 与 RowTile 同一条行首线、同一行高
        child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Icon(problem ? Icons.cloud_off_rounded : Icons.computer_rounded,
              size: Layout.rowIcon, color: problem ? p.warning : (s.running ? p.text2 : p.text3)),
          const SizedBox(width: Sp.x4),
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
              Row(children: [
                Expanded(
                  child: SwapSwitcher(
                    child: Text(computerStateLabel(s.state),
                        key: ValueKey(s.state),
                        style: context.text.titleMedium?.copyWith(color: problem ? p.warning : null)),
                  ),
                ),
                if (hint != null) SwapSwitcher(child: RowHint(hint, key: ValueKey(hint), warn: computerHintWarn(s))),
                if (onOpen != null) Icon(Icons.chevron_right_rounded, color: p.text3, size: Layout.rowIcon),
              ]),
              const SizedBox(height: Sp.x1),
              Text(computerDetail(s), style: context.text.bodySmall, maxLines: 2, overflow: TextOverflow.ellipsis),
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
                        key: ValueKey('oom-${s.oomKills}'),
                        padding: const EdgeInsets.only(top: Sp.x2),
                        child: Text(oom, style: context.text.bodySmall?.copyWith(color: p.warning)),
                      ),
              ),
            ]),
          ),
        ]),
      ),
    );
    return onOpen == null
        ? tile
        : InkWell(onTap: onOpen, borderRadius: BorderRadius.circular(Radii.inner), child: tile);
  }
}

class _JobRow extends ConsumerWidget {
  const _JobRow({super.key, required this.job, required this.cancelling, required this.onCancel});
  final JobInfo job;
  final bool cancelling;
  final VoidCallback onCancel;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final p = context.palette;
    return RowTile(
      leading: SizedBox.square(dimension: Layout.rowIcon, child: Center(child: PulseDot(color: p.accent, size: 8))),
      title: job.title,
      subtitle: jobRowSubtitle(job),
      trailing: TextButton(onPressed: cancelling ? null : onCancel, child: Text(cancelling ? '正在取消' : '取消')),
      onTap: () => showJobLog(context, ref, job),
    );
  }
}

/// 常驻服务一行（v1.82）。健康点：在跑 = 任务卡同款脉冲（JobStatusMark），等重启 = 警示色脉冲，停了 = 警示图标。
class _ServiceRow extends ConsumerWidget {
  const _ServiceRow({super.key, required this.service, required this.busy, required this.onRestart});
  final ServiceInfo service;
  final bool busy;
  final VoidCallback onRestart;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final p = context.palette;
    final v = service;
    final mark = switch (v.health) {
      ServiceHealth.up => const JobStatusMark(JobTone.running),
      ServiceHealth.restarting => PulseDot(color: p.warning, size: 8),
      ServiceHealth.gaveUp => const JobStatusMark(JobTone.problem),
    };
    return Semantics(
      label: serviceSemantics(v),
      child: RowTile(
        leading: SizedBox.square(
          dimension: Layout.rowIcon,
          child: Center(child: SwapSwitcher(child: KeyedSubtree(key: ValueKey(v.health), child: mark))),
        ),
        title: v.job.title,
        problem: v.health == ServiceHealth.gaveUp ? '已停止' : null,
        subtitle: serviceLine(v),
        trailing: TextButton(onPressed: busy ? null : onRestart, child: Text(busy ? '正在重启' : serviceAction(v.health))),
        onTap: () => showJobLog(context, ref, v.job),
      ),
    );
  }
}
