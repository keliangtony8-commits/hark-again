// 电脑详情页的两节（v1.27）：和 ComputerSection 读同一个 computerProvider(工作区)，不另外请求。
//   正在运行的程序       ← 只在运行中且有程序时出现；按 CPU 排，最多 8 个
//     python train.py --epochs 10
//     CPU 88% · 内存 200 MB · 运行 3 分 05 秒
//   磁盘                              清理 12 MB
//     已用 2.6 GB，上限 3 GB（v1.31 配额，服务器不限时不出现）  ▬▬▬▬▬▬▬▭  快满 / 满了 → 条变警示色 + 一句后果
//     文件 / 装的软件 / 任务日志 / 长输出存档 / 下载缓存（0 字节的不列，行尾是大小）
//     装过的工具  pip 12 个 · npm 2 个  →  弹层列出名字和版本
//   内存（v1.94）              ← 只在运行中且排得出是谁占的时出现（服务器 app/memory_view.py）
//     已用 800 MB，上限 1 GB  ▬▬▬▬▬▬▭  快满了 → 条变警示色 + 点名最大的那个
//     大任务      后台任务 · 2 个进程 · 占 44%       350 MB   ▬▬▬▬▭  点 = 看它的完整日志
//     python bot.py  程序 · PID 9 · 占 15%            120 MB
//     其它        系统和零碎小程序 · 占 41%           330 MB
//   最近 7 天谁写得最多（v1.98）  ← 有结算账的已结束任务才出现（服务器 job_disk.leaders），不用开机
//     按任务结束时数的账；写下的文件不会被清理……（头一句）
//     装依赖     2 天前 · 主要写在 node_modules/ · 日志 2 MB      302 MB  ▬▬▬▭  点 = 看它的完整日志与磁盘明细
//   正在监听的端口（v1.30）     ← 只在运行中且有端口时出现
//     端口 8000  python3 -m http.server …       ↗   点 = 签预览链接并用浏览器打开；长按 = 复制链接
//     端口 5173  只监听本机，预览打不开（要监听 0.0.0.0）  ← 警示“打不开”，不可点
// “清理”先确认，删的东西由服务器 app/computer.py cleanup 定（存档、已结束任务日志、缓存），文案规则在 models/computer.dart。
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../blocks/job_block.dart';
import '../../core/api.dart';
import '../../core/links.dart';
import '../../models/computer.dart';
import '../../models/job.dart';
import '../../models/preview.dart';
import '../../theme/app_theme.dart';
import '../../theme/tokens.dart';
import '../../ui/format.dart';
import '../../ui/glass.dart';
import '../../ui/kit.dart';
import '../../ui/motion.dart';
import '../../ui/sheets.dart';
import 'computer_section.dart';

/// 正在运行的程序。
class ProcessSection extends ConsumerWidget {
  const ProcessSection({super.key, required this.ws, this.delay = Duration.zero});
  final String ws;
  final Duration delay;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final s = ref.watch(computerProvider(ws)).value;
    final list = s != null && s.running ? s.processes : const <ComputerProcess>[];
    return RiseSwitcher(
      child: list.isEmpty
          ? const SizedBox.shrink(key: ValueKey('noproc'))
          : FadeSlideIn(
              key: const ValueKey('proc'),
              delay: delay,
              child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                SectionTitle('正在运行的程序', count: list.length),
                GlassGroup(children: [
                  for (final p in list)
                    RowTile(
                      key: ValueKey('proc-${p.pid}'),
                      icon: Icons.terminal_rounded,
                      title: processTitle(p),
                      subtitle: processLine(p),
                    ),
                ]),
              ]),
            ),
    );
  }
}

/// 内存去哪了（v1.94）：整台已用 + 按大小排的占用者，每行一条占比细条；后台任务 / 服务点了看日志。
class MemorySection extends ConsumerWidget {
  const MemorySection({super.key, required this.ws, this.delay = Duration.zero});
  final String ws;
  final Duration delay;

  JobInfo? _job(ComputerStatus s, MemoryRow r) {
    if (r.id == null) return null;
    for (final j in s.jobs) {
      if (j.id == r.id) return j;
    }
    for (final v in s.services) {
      if (v.job.id == r.id) return v.job;
    }
    return null;
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final s = ref.watch(computerProvider(ws)).value;
    final v = s == null ? null : memoryViewOf(s);
    return RiseSwitcher(
      child: v == null
          ? const SizedBox.shrink(key: ValueKey('nomem'))
          : FadeSlideIn(
              key: const ValueKey('mem'),
              delay: delay,
              child: Semantics(
                container: true,
                label: memorySemantics(v),
                excludeSemantics: true,
                child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                  const SectionTitle('内存'),
                  GlassGroup(children: [
                    _MemoryHead(v),
                    for (final (i, r) in v.rows.indexed)
                      _MemoryRowTile(
                        key: ValueKey('mem-${r.key}'),
                        icon: switch (r.owner) {
                          MemoryOwner.job => Icons.work_outline_rounded,
                          MemoryOwner.service => Icons.dns_outlined,
                          MemoryOwner.process => Icons.terminal_rounded,
                        },
                        title: memoryRowTitle(r),
                        line: memoryRowLine(r),
                        bytes: r.memory,
                        share: r.share,
                        warn: i == 0 && v.tight,
                        onTap: switch (_job(s!, r)) { final j? => () => showJobLog(context, ref, j), _ => null },
                      ),
                    if (v.other > 0)
                      _MemoryRowTile(
                        key: const ValueKey('mem-other'),
                        icon: Icons.blur_on_rounded,
                        title: memoryOtherTitle,
                        line: memoryOtherLine(v),
                        bytes: v.other,
                        share: v.otherShare,
                      ),
                  ]),
                ]),
              ),
            ),
    );
  }
}

/// 头一行：已用 / 上限 + 条；快满了条变警示色、下面一句点名最大的（与磁盘配额行同一画法）。
class _MemoryHead extends StatelessWidget {
  const _MemoryHead(this.v);
  final MemoryView v;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final line = memoryViewLine(v);
    final note = memoryTightNote(v);
    final color = v.tight ? p.warning : p.text2;
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: Sp.x4, vertical: Sp.x3 - 2), // 与 RowTile 同一条行首线
      child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Icon(Icons.memory_rounded, size: Layout.rowIcon, color: color),
        const SizedBox(width: Sp.x4),
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            SwapSwitcher(child: Text(line, key: ValueKey(line), style: context.text.titleMedium)),
            if (v.ratio != null)
              Padding(
                padding: const EdgeInsets.only(top: Sp.x2),
                child: MeterBar(value: v.ratio!, height: Sp.x1, color: color),
              ),
            RiseSwitcher(
              child: note == null
                  ? const SizedBox.shrink(key: ValueKey('nonote'))
                  : Padding(
                      key: const ValueKey('note'),
                      padding: const EdgeInsets.only(top: Sp.x2),
                      child: Text(note, style: context.text.bodySmall?.copyWith(color: p.warning)),
                    ),
            ),
          ]),
        ),
      ]),
    );
  }
}

/// 一个占用者（内存一节、v1.98 磁盘谁写得最多共用）：图标 · 名字 / 归属与占比 · 大小，下面一条占比细条（数变了条平滑走过去）。
class _MemoryRowTile extends StatelessWidget {
  const _MemoryRowTile(
      {super.key, required this.icon, required this.title, required this.line, this.bytes = 0, this.size, required this.share, this.warn = false, this.onTap});
  final IconData icon;
  final String title, line;
  final int bytes;

  /// 行尾的字；不给 = formatSize(bytes)（磁盘一节要带“+”）。
  final String? size;
  final double share;
  final bool warn;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final size = this.size ?? formatSize(bytes);
    final tile = Padding(
      padding: const EdgeInsets.symmetric(horizontal: Sp.x4, vertical: Sp.x3 - 2),
      child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Icon(icon, size: Layout.rowIcon, color: warn ? p.warning : p.text2),
        const SizedBox(width: Sp.x4),
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            Row(crossAxisAlignment: CrossAxisAlignment.baseline, textBaseline: TextBaseline.alphabetic, children: [
              Expanded(child: Text(title, maxLines: 1, overflow: TextOverflow.ellipsis, style: context.text.titleMedium)),
              const SizedBox(width: Sp.x3),
              SwapSwitcher(child: RowHint(size, key: ValueKey(size))),
            ]),
            Padding(
              padding: const EdgeInsets.only(top: Sp.x1),
              child: Text(line, maxLines: 1, overflow: TextOverflow.ellipsis, style: context.text.bodySmall),
            ),
            Padding(
              padding: const EdgeInsets.only(top: Sp.x2),
              child: MeterBar(value: share, height: Sp.x1, color: warn ? p.warning : p.text2),
            ),
          ]),
        ),
      ]),
    );
    return onTap == null ? tile : InkWell(onTap: onTap, child: tile);
  }
}

/// 最近 7 天谁写得最多（v1.98）：和内存一节同一种行（图标 · 名字 / 说明 · 大小 + 占比细条），点了看完整日志。
class DiskJobsSection extends ConsumerWidget {
  const DiskJobsSection({super.key, required this.ws, this.delay = Duration.zero});
  final String ws;
  final Duration delay;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final s = ref.watch(computerProvider(ws)).value;
    final rows = s == null ? const <DiskJob>[] : diskJobRows(s);
    return RiseSwitcher(
      child: rows.isEmpty
          ? const SizedBox.shrink(key: ValueKey('nodiskjobs'))
          : FadeSlideIn(
              key: const ValueKey('diskjobs'),
              delay: delay,
              child: Semantics(
                container: true,
                label: diskJobsSemantics(s!),
                excludeSemantics: true,
                child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                  const SectionTitle(diskJobsTitle),
                  GlassGroup(children: [
                    Padding(
                      padding: const EdgeInsets.fromLTRB(Sp.x4, Sp.x3 - 2, Sp.x4, 0),
                      child: SwapSwitcher(
                        child: Text(diskJobsNote(s), key: ValueKey(diskJobsNote(s)), style: context.text.bodySmall),
                      ),
                    ),
                    for (final r in rows)
                      _MemoryRowTile(
                        key: ValueKey('diskjob-${r.job.id}'),
                        icon: r.disk.top.isNotEmpty && r.disk.top.first.path == '.home/' ? Icons.extension_outlined : Icons.work_outline_rounded,
                        title: r.job.title,
                        line: diskJobLine(r),
                        size: diskJobSize(r),
                        share: diskJobShare(s, r),
                        onTap: () => showJobLog(context, ref, r.job),
                      ),
                  ]),
                ]),
              ),
            ),
    );
  }
}

/// 正在监听的端口：点一下预览。
class PortsSection extends ConsumerStatefulWidget {
  const PortsSection({super.key, required this.ws, this.delay = Duration.zero});
  final String ws;
  final Duration delay;

  @override
  ConsumerState<PortsSection> createState() => _PortsSectionState();
}

class _PortsSectionState extends ConsumerState<PortsSection> {
  int? _busy;

  Future<void> _go(ListeningPort port, {bool copy = false}) async {
    setState(() => _busy = port.port);
    try {
      final url = await ref.read(computerProvider(widget.ws).notifier).preview(port.port);
      if (!mounted) return;
      if (copy) {
        Clipboard.setData(ClipboardData(text: url));
        showToast(context, '预览链接已复制（24 小时内有效）');
      } else {
        await openUrl(url);
      }
    } on ApiError catch (e) {
      if (mounted) showToast(context, e.isNetwork ? '无法连接服务器' : e.message);
    } finally {
      if (mounted) setState(() => _busy = null);
    }
  }

  @override
  Widget build(BuildContext context) {
    final s = ref.watch(computerProvider(widget.ws)).value;
    final list = s != null && s.running ? s.ports : const <ListeningPort>[];
    return RiseSwitcher(
      child: list.isEmpty
          ? const SizedBox.shrink(key: ValueKey('noports'))
          : FadeSlideIn(
              key: const ValueKey('ports'),
              delay: widget.delay,
              child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                SectionTitle('正在监听的端口', count: list.length),
                GlassGroup(children: [
                  for (final p in list)
                    RowTile(
                      key: ValueKey('port-${p.port}'),
                      icon: Icons.language_rounded,
                      title: portTitle(p.port),
                      subtitle: p.loopback ? '只监听本机，要让服务监听 0.0.0.0' : portLine(p),
                      problem: p.loopback ? '打不开' : null,
                      trailing: p.loopback
                          ? null
                          : SwapSwitcher(
                              child: _busy == p.port
                                  ? const RowHint('正在打开', key: ValueKey('busy'))
                                  : const Icon(Icons.open_in_new_rounded, size: 18, key: ValueKey('open')),
                            ),
                      onTap: p.loopback || _busy != null ? null : () => _go(p),
                      onLongPress: p.loopback || _busy != null ? null : () => _go(p, copy: true),
                    ),
                ]),
              ]),
            ),
    );
  }
}

/// 磁盘：按用途拆开 + 装过的工具 + 一键清理。
class StorageSection extends ConsumerStatefulWidget {
  const StorageSection({super.key, required this.ws, this.delay = Duration.zero, this.onFiles});
  final String ws;
  final Duration delay;

  /// 点“文件”一行（打开文件弹层）。
  final VoidCallback? onFiles;

  @override
  ConsumerState<StorageSection> createState() => _StorageSectionState();
}

class _StorageSectionState extends ConsumerState<StorageSection> {
  bool _cleaning = false;

  static const _icons = {
    'files': Icons.folder_outlined,
    'installed': Icons.extension_outlined,
    'logs': Icons.receipt_long_outlined,
    'spill': Icons.inventory_2_outlined,
    'cache': Icons.cached_rounded,
  };

  Future<void> _clean() async {
    if (!await confirmDanger(context, title: '清理这台电脑？', text: cleanupText, action: '清理')) return;
    setState(() => _cleaning = true);
    try {
      final freed = await ref.read(computerProvider(widget.ws).notifier).cleanup();
      if (mounted) showToast(context, cleanupDone(freed));
    } on ApiError catch (e) {
      if (mounted) showToast(context, e.isNetwork ? '无法连接服务器，清理失败' : e.message);
    } finally {
      if (mounted) setState(() => _cleaning = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final s = ref.watch(computerProvider(widget.ws)).value;
    if (s == null) return const SizedBox.shrink();
    final label = cleanupLabel(s.storage);
    return FadeSlideIn(
      delay: widget.delay,
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        SectionTitle('磁盘',
            trailing: SwapSwitcher(
              child: label == null
                  ? const SizedBox.shrink(key: ValueKey('noclean'))
                  : TextButton(
                      key: const ValueKey('clean'),
                      onPressed: _cleaning ? null : _clean,
                      child: Text(_cleaning ? '正在清理' : label),
                    ),
            )),
        GlassGroup(children: [
          if (s.diskLimit != null) _QuotaTile(s),
          for (final (key, name, line, bytes) in storageRows(s.storage))
            RowTile(
              key: ValueKey('disk-$key'),
              icon: _icons[key],
              title: name,
              subtitle: line,
              trailing: SwapSwitcher(child: RowHint(formatSize(bytes), key: ValueKey('$key-$bytes'))),
              onTap: key == 'files' ? widget.onFiles : null,
            ),
          RowTile(
            icon: Icons.handyman_outlined,
            title: '装过的工具',
            subtitle: toolsSummary(s.tools),
            onTap: s.tools.isEmpty ? null : () => _showTools(context, s.tools),
          ),
        ]),
      ]),
    );
  }
}

/// 磁盘配额：已用 / 上限 + 细条；快满、满了条变警示色并说清后果（与状态块的内存条同一画法）。
class _QuotaTile extends StatelessWidget {
  const _QuotaTile(this.s);
  final ComputerStatus s;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final note = computerDiskNote(s);
    final line = computerDiskLine(s);
    return Semantics(
      container: true,
      label: [line, ?note].join('，'),
      excludeSemantics: true,
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: Sp.x4, vertical: Sp.x3 - 2), // 与 RowTile 同一条行首线
        child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Icon(Icons.storage_rounded, size: Layout.rowIcon, color: s.diskTight ? p.warning : p.text2),
          const SizedBox(width: Sp.x4),
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
              SwapSwitcher(child: Text(line, key: ValueKey(line), style: context.text.titleMedium)),
              Padding(
                padding: const EdgeInsets.only(top: Sp.x2),
                child: MeterBar(value: computerDiskRatio(s) ?? 0, height: Sp.x1, color: s.diskTight ? p.warning : p.text2),
              ),
              RiseSwitcher(
                child: note == null
                    ? const SizedBox.shrink(key: ValueKey('nonote'))
                    : Padding(
                        key: ValueKey('note-${s.diskLevel}'),
                        padding: const EdgeInsets.only(top: Sp.x2),
                        child: Text(note, style: context.text.bodySmall?.copyWith(color: p.warning)),
                      ),
              ),
            ]),
          ),
        ]),
      ),
    );
  }
}

void _showTools(BuildContext context, List<InstalledTool> tools) => showAppScrollSheet<void>(
      context,
      builder: (ctx) => Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(Sp.x5, Sp.x2, Sp.x5, Sp.x1),
          child: Text('装过的工具', style: ctx.text.titleLarge),
        ),
        Padding(
          padding: const EdgeInsets.fromLTRB(Sp.x5, 0, Sp.x5, Sp.x3),
          child: Text('装在工作区 ~/.local 里，以后的对话和后台任务都能直接用；不含系统预装的。', style: ctx.text.bodySmall),
        ),
        SheetList(children: [
          GlassGroup(children: [
            for (final (i, t) in tools.indexed)
              FadeSlideIn(
                key: ValueKey('tool-${t.kind}-${t.name}'),
                delay: Motion.stagger(i.clamp(0, 8)),
                child: RowTile(
                  icon: t.kind == 'npm' ? Icons.javascript_rounded : Icons.code_rounded,
                  title: t.name,
                  subtitle: t.kind,
                  trailing: t.version.isEmpty ? null : RowHint(t.version),
                ),
              ),
          ]),
        ]),
      ]),
    );
