// 后台任务卡：助手在项目沙盒里放到后台跑的活（装依赖、训练、爬取）。
//   [●] 训练模型                         1 分 05 秒
//   $ python train.py --epochs 20
//   ┌ 日志最后几行（等宽，实时）┐
//   运行中                                  取消
// 运行中每 Timing.jobPoll 问一次 /api/jobs/{id}，用时每秒本地跳；结束后状态点换成结论图标，按钮换成“完整日志”。
// 结束时服务器会在这段对话里接着说一轮（followup=pending）：卡片继续问到它说完，再让聊天页刷新一次（BlockActions.onJobSettled），
// 助手的那句结论就自己出现在下面。只有在这张卡上亲眼看着它从“运行中”结束才触发刷新，翻历史不会。
// v2.18 结束后它改了哪些文件：日志下面嵌一块 ChangesPanel（同消息里的改动卡，scope = job），撤销走 /api/jobs/{id}/changes/undo。
import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/api.dart';
import '../models/block.dart';
import '../models/changes.dart';
import '../models/job.dart';
import '../theme/app_theme.dart';
import '../theme/tokens.dart';
import '../ui/glass_mode.dart';
import '../ui/kit.dart';
import '../ui/motion.dart';
import '../ui/sheets.dart';
import 'block_actions.dart';
import 'block_frame.dart';
import 'changes_block.dart';

const _mono = 'monospace';

/// 等服务器“接着说”最多等多久（worker 每 5 秒一轮，模型回一句通常十几秒）。
const _replyWait = Duration(seconds: 90);

class JobBlockView extends ConsumerStatefulWidget {
  const JobBlockView(this.block, {super.key});
  final JobBlock block;

  @override
  ConsumerState<JobBlockView> createState() => _JobBlockViewState();
}

class _JobBlockViewState extends ConsumerState<JobBlockView> {
  late JobInfo _job = JobInfo.fromBlock(widget.block);
  late DateTime _polledAt = DateTime.now();
  Timer? _poll, _clock;
  DateTime? _endedAt; // 本卡看着它结束的时刻（等“接着说”的计时起点）
  bool _sawRunning = false, _settledSent = false, _cancelling = false;

  Api get _api => ref.read(apiProvider);

  @override
  void initState() {
    super.initState();
    if (_job.running) {
      _sawRunning = true;
      _poll = Timer.periodic(Timing.jobPoll, (_) => _refresh());
      _clock = Timer.periodic(Timing.clockTick, (_) => mounted && _job.running ? setState(() {}) : null);
      WidgetsBinding.instance.addPostFrameCallback((_) => _refresh()); // TickerMode 要等 initState 之后才能读
    }
  }

  @override
  void dispose() {
    _poll?.cancel();
    _clock?.cancel();
    super.dispose();
  }

  Future<void> _refresh() async {
    if (!mounted || !TickerMode.valuesOf(context).enabled) return;
    try {
      final j = JobInfo.fromJson(await _api.get('/api/jobs/${widget.block.id}') as Map<String, dynamic>);
      if (mounted) _apply(j);
    } on ApiError catch (e) {
      if (e.status == 404) _stop(); // 项目被删了
    }
  }

  void _apply(JobInfo j) {
    setState(() {
      _job = j;
      _polledAt = DateTime.now();
    });
    if (j.running) return;
    _clock?.cancel();
    _endedAt ??= DateTime.now();
    final waited = DateTime.now().difference(_endedAt!) > _replyWait;
    if (j.awaitingReply && !waited) return;
    _stop();
    if (_sawRunning && !_settledSent) {
      _settledSent = true;
      BlockActions.of(context)?.onJobSettled?.call();
    }
  }

  void _stop() {
    _poll?.cancel();
    _clock?.cancel();
  }

  Future<void> _cancel() async {
    setState(() => _cancelling = true);
    try {
      _apply(JobInfo.fromJson(await _api.post('/api/jobs/${widget.block.id}/cancel') as Map<String, dynamic>));
    } on ApiError catch (e) {
      if (mounted) showToast(context, e.isNetwork ? '无法连接服务器，取消失败' : e.message);
    } finally {
      if (mounted) setState(() => _cancelling = false);
    }
  }

  /// v2.18 撤销它改的文件：成功换上服务器回的任务（改动区变“已撤销”）；失败返回原因。
  Future<String?> _undoChanges() async {
    try {
      final j = JobInfo.fromJson(await _api.post('/api/jobs/${widget.block.id}/changes/undo') as Map<String, dynamic>);
      if (mounted) setState(() => _job = j);
      return null;
    } on ApiError catch (e) {
      return e.isNetwork ? '无法连接服务器，请稍后重试' : e.message;
    }
  }

  /// 用时：运行中 = 上次问到的 + 本地流逝（跳秒不用每秒请求）；结束了就是服务器给的。
  Duration get _elapsed => _job.running ? _job.elapsed + DateTime.now().difference(_polledAt) : _job.elapsed;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final j = _job;
    final tone = jobTone(j.state, autoStopped: j.autoStopped);
    final tail = jobTailLines(j.tail, Layout.jobLogLines);
    final small = context.text.labelSmall;
    return Semantics(
      container: true,
      label: jobSemantics(j.withElapsed(_elapsed)),
      child: BlockFrame(
        padding: const EdgeInsets.fromLTRB(Sp.x4, Sp.x3, Sp.x2, Sp.x1),
        child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          Padding(
            padding: const EdgeInsets.only(right: Sp.x2),
            child: Row(children: [
              SwapSwitcher(child: JobStatusMark(tone, key: ValueKey(tone))),
              const SizedBox(width: Sp.x2),
              Expanded(child: Text(j.title, style: context.text.labelLarge, maxLines: 1, overflow: TextOverflow.ellipsis)),
              const SizedBox(width: Sp.x2),
              ExcludeSemantics(child: Text(jobDuration(_elapsed), style: small?.copyWith(color: p.text3))),
            ]),
          ),
          const SizedBox(height: Sp.x1),
          Padding(
            padding: const EdgeInsets.only(right: Sp.x2),
            child: Text('\$ ${j.command.split('\n').first}',
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: TextStyle(fontFamily: _mono, fontSize: Fs.xs, color: p.text3)),
          ),
          const SizedBox(height: Sp.x2),
          Padding(
            padding: const EdgeInsets.only(right: Sp.x2),
            child: AnimatedSize(
              duration: context.motion(Motion.base),
              curve: Motion.ease,
              alignment: Alignment.topCenter,
              child: Container(
                width: double.infinity,
                padding: const EdgeInsets.symmetric(horizontal: Sp.x3, vertical: Sp.x2),
                decoration: BoxDecoration(color: context.tileFill, borderRadius: BorderRadius.circular(Radii.inner)),
                child: Text(
                  tail.isEmpty ? (j.running ? '等待输出…' : '（没有输出）') : tail,
                  maxLines: Layout.jobLogLines,
                  overflow: TextOverflow.clip,
                  style: TextStyle(fontFamily: _mono, fontSize: Fs.xs, height: 1.45, color: tail.isEmpty ? p.text3 : p.text2),
                ),
              ),
            ),
          ),
          // 停掉 / 失败的原因（护栏、内存超限或打满、放弃重启）：就在日志下面，和日志一起读
          RiseSwitcher(
            child: j.showsReason
                ? Padding(
                    key: const ValueKey('reason'),
                    padding: const EdgeInsets.only(top: Sp.x2, right: Sp.x2),
                    child: ExcludeSemantics(
                      child: Text(j.stopReason!, style: small?.copyWith(color: p.text2), maxLines: 2, overflow: TextOverflow.ellipsis),
                    ),
                  )
                : const SizedBox.shrink(key: ValueKey('none')),
          ),
          // v1.90 在跑时它占多少：CPU 条（平滑过渡）+ 内存 / 进程数；问不到就不出现（不画成 0）
          RiseSwitcher(
            child: j.running && j.usage != null
                ? Padding(
                    key: const ValueKey('usage'),
                    padding: const EdgeInsets.only(top: Sp.x2, right: Sp.x2),
                    child: _UsageLine(j.usage!, max: j.memoryMax, near: j.memoryNear),
                  )
                : const SizedBox.shrink(key: ValueKey('nousage')),
          ),
          // v1.92 整台沙盒内存快满了：提醒一句（系统先结束普通后台任务）
          RiseSwitcher(
            child: j.boxTight
                ? Padding(
                    key: const ValueKey('tight'),
                    padding: const EdgeInsets.only(top: Sp.x2, right: Sp.x2),
                    child: ExcludeSemantics(
                      child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                        Icon(Icons.memory_rounded, size: Fs.sm, color: p.warning),
                        const SizedBox(width: Sp.x1),
                        Expanded(child: Text(jobBoxLabel(j.box!), style: small?.copyWith(color: p.warning), maxLines: 2, overflow: TextOverflow.ellipsis)),
                      ]),
                    ),
                  )
                : const SizedBox.shrink(key: ValueKey('roomy')),
          ),
          // v1.96 它占了多少磁盘：写了多少文件、最多的是哪一组、日志多大（写了东西或日志够大才出现）
          RiseSwitcher(
            child: jobDiskShown(j.disk)
                ? Padding(
                    key: const ValueKey('disk'),
                    padding: const EdgeInsets.only(top: Sp.x2, right: Sp.x2),
                    child: ExcludeSemantics(
                      child: Row(children: [
                        Icon(Icons.save_outlined, size: Fs.sm, color: p.text3),
                        const SizedBox(width: Sp.x1),
                        Expanded(
                          child: SwapSwitcher(
                            child: Text(jobDiskLabel(j.disk!),
                                key: ValueKey(jobDiskLabel(j.disk!)),
                                style: small?.copyWith(color: p.text3, fontFeatures: const [FontFeature.tabularFigures()]),
                                maxLines: 1,
                                overflow: TextOverflow.ellipsis),
                          ),
                        ),
                      ]),
                    ),
                  )
                : const SizedBox.shrink(key: ValueKey('nodisk')),
          ),
          // v2.18 它改了哪些文件（结束了才有）：可点开看 diff、整份撤销
          RiseSwitcher(
            child: jobChangesShown(j.changes)
                ? Padding(
                    key: const ValueKey('changes'),
                    padding: const EdgeInsets.only(top: Sp.x3),
                    child: ChangesPanel(j.changes!, scope: ChangesScope.job, onUndo: _undoChanges),
                  )
                : const SizedBox.shrink(key: ValueKey('nochanges')),
          ),
          Row(children: [
            Expanded(
              child: Align(
                alignment: Alignment.centerLeft,
                child: SwapSwitcher(
                  child: Text(
                    jobFootLabel(j),
                    key: ValueKey(jobFootLabel(j)),
                    style: small?.copyWith(
                        color: tone == JobTone.problem ? p.warning : p.text2,
                        fontWeight: tone == JobTone.problem ? Weights.title : null),
                  ),
                ),
              ),
            ),
            SwapSwitcher(
              child: j.running
                  ? TextButton(key: const ValueKey('cancel'), onPressed: _cancelling ? null : _cancel, child: Text(_cancelling ? '正在取消' : '取消'))
                  : TextButton(key: const ValueKey('log'), onPressed: () => showJobLog(context, ref, j), child: const Text('完整日志')),
            ),
          ]),
        ]),
      ),
    );
  }
}

/// CPU 35%  ▬▬▬▬▭▭▭▭  内存 120.0 MB / 512.0 MB · 3 个进程（快到上限时内存字变警示色）
class _UsageLine extends StatelessWidget {
  const _UsageLine(this.u, {this.max, this.near = false});
  final JobUsage u;
  final int? max;
  final bool near;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final small = context.text.labelSmall?.copyWith(color: p.text3, fontFeatures: const [FontFeature.tabularFigures()]);
    final hot = u.cpu >= jobCpuHot;
    return ExcludeSemantics(// 整张卡的读屏句子（jobSemantics）已经带上占用
        child: Row(children: [
          Text('CPU ${jobCpuLabel(u.cpu)}', style: hot ? small?.copyWith(color: p.warning) : small),
          const SizedBox(width: Sp.x2),
          Expanded(child: MeterBar(value: u.cpu / 100, height: Sp.x1, color: hot ? p.warning : p.text2)),
          const SizedBox(width: Sp.x2),
          Flexible(
              child: Text(jobMemoryLabel(u, max: max),
                  style: near ? small?.copyWith(color: p.warning) : small, maxLines: 1, overflow: TextOverflow.ellipsis)),
        ]),
    );
  }
}

/// 卡头的状态点 / 结论图标（后台任务卡和用户命令卡共用）。
class JobStatusMark extends StatelessWidget {
  const JobStatusMark(this.tone, {super.key});
  final JobTone tone;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    return SizedBox.square(
      dimension: 18,
      child: Center(
        child: switch (tone) {
          JobTone.running => PulseDot(color: p.accent, size: 8),
          JobTone.ok => Icon(Icons.check_circle_outline_rounded, size: 18, color: p.text2),
          JobTone.problem => Icon(Icons.error_outline_rounded, size: 18, color: p.warning),
          JobTone.quiet => Icon(Icons.do_not_disturb_on_outlined, size: 18, color: p.text3),
        },
      ),
    );
  }
}

/// 完整日志（最后 2 万字）：可选中复制。
Future<void> showJobLog(BuildContext context, WidgetRef ref, JobInfo j) {
  final full = ref.read(apiProvider).get('/api/jobs/${j.id}?tail=20000');
  return showAppScrollSheet<void>(
    context,
    title: '完整日志',
    builder: (ctx) {
      final p = ctx.palette;
      return Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(Sp.x5, Sp.x2, Sp.x3, Sp.x3),
          child: Row(children: [
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text('${jobStateLabel(j)} · ${jobDuration(j.elapsed)}', style: ctx.text.labelSmall),
                const SizedBox(height: Sp.x1),
                Text(j.title, style: ctx.text.titleLarge, maxLines: 2, overflow: TextOverflow.ellipsis),
                // v1.96 磁盘明细：拉到的最新一份优先（电脑页的任务行没带 disk），没有就用卡上的
                FutureBuilder(
                  future: full,
                  builder: (_, snap) {
                    final d = (snap.hasData ? JobDisk.tryParse((snap.data as Map)['disk']) : null) ?? j.disk;
                    return RiseSwitcher(
                      child: d == null
                          ? const SizedBox.shrink(key: ValueKey('nodisk'))
                          : Padding(
                              key: const ValueKey('disk'),
                              padding: const EdgeInsets.only(top: Sp.x1),
                              child: Text(jobDiskDetail(d), style: ctx.text.labelSmall?.copyWith(color: p.text3)),
                            ),
                    );
                  },
                ),
              ]),
            ),
            FutureBuilder(
              future: full,
              builder: (_, snap) => CopyAction(text: snap.hasData ? '${(snap.data as Map)['tail'] ?? ''}' : j.tail, tooltip: '复制日志'),
            ),
          ]),
        ),
        FutureBuilder(
          future: full,
          builder: (ctx, snap) {
            final text = snap.hasData ? '${(snap.data as Map)['tail'] ?? ''}' : j.tail;
            return SheetList(padding: const EdgeInsets.fromLTRB(Sp.x5, 0, Sp.x5, Sp.x5), children: [
              FadeSwitcher(
                child: SelectableText(
                  text.trim().isEmpty ? '（没有输出）' : text.trimRight(),
                  key: ValueKey(snap.hasData),
                  style: TextStyle(fontFamily: _mono, fontSize: Fs.xs, height: 1.5, color: p.text2),
                ),
              ),
            ]);
          },
        ),
      ]);
    },
  );
}
