// v3.5.3 性能自检（core/perf_probe.dart）：入口在“关于”页，性能浮层打开时多一行“性能自检 ›”。
// 点了 → 回到“我的”页，在它上面依次跑 A–H（每个约 2.5 秒，程序化来回匀速滚动），跑完恢复全开、推到结果页（/me/perf-probe）。
// 结果页 = 顶部设备 / 渲染信息 + 一张表，用户截一张图即可。
import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../../core/perf_probe.dart';
import '../../theme/app_theme.dart';
import '../../theme/tokens.dart';
import '../../ui/glass.dart';
import '../../ui/kit.dart';
import '../../ui/sub_page.dart';
import 'me_screen.dart';

/// 从关于页开始一次自检（跑完自己推到结果页）。
Future<void> startPerfProbe(BuildContext context, {PerfProbeRunner? runner}) async {
  if (PerfProbeRunner.running) return;
  final router = GoRouter.of(context);
  showToast(context, '性能自检约 30 秒，期间别碰屏幕');
  router.go('/me');
  await Future<void>.delayed(const Duration(milliseconds: 900)); // 等返回转场结束
  final device = await perfDeviceInfo();
  await (runner ?? PerfProbeRunner()).run(
    device: device,
    locate: () {
      final root = WidgetsBinding.instance.rootElement;
      return root == null ? null : findScrollUnder<MeScreen>(root);
    },
  );
  router.push('/me/perf-probe');
}

class PerfProbeScreen extends StatelessWidget {
  const PerfProbeScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final r = PerfProbeRunner.last;
    final p = context.palette;
    final small = context.text.bodySmall!.copyWith(color: p.text, fontFeatures: const [FontFeature.tabularFigures()]);
    final dim = small.copyWith(color: p.text2);
    String ms(double v) => v.toStringAsFixed(1);
    String hz(double v) => v.toStringAsFixed(0);
    Widget cell(String s, {TextStyle? style, TextAlign align = TextAlign.right}) =>
        Padding(padding: const EdgeInsets.symmetric(vertical: 6, horizontal: 3), child: Text(s, style: style ?? small, textAlign: align));
    return SubPage(
      title: const Text('性能自检'),
      body: PageBody(children: [
        if (r == null)
          const PageIntro(line: '还没有结果：到“关于”页打开性能浮层后点“性能自检”。')
        else ...[
          GlassCardInfo(lines: [
            if (perfNeedsHzHint(r)) perfFlymeHint,
            perfHzLine(r),
            for (final e in r.device.entries) '${e.key}：${e.value}',
            '预算：${ms(r.budgetMs)} ms/帧 · 可滚动 ${r.scrollExtent.round()} px',
            if (r.note != null) r.note!,
          ]),
          const SizedBox(height: Sp.x3),
          Table(
            columnWidths: const {0: FlexColumnWidth(3.2)},
            defaultVerticalAlignment: TableCellVerticalAlignment.middle,
            border: TableBorder(horizontalInside: BorderSide(color: context.hairline)),
            children: [
              TableRow(children: [
                cell('变体', style: dim, align: TextAlign.left),
                cell('光栅均', style: dim),
                cell('p90', style: dim),
                cell('最大', style: dim),
                cell('帧数', style: dim),
                cell('>预算', style: dim),
                cell('fps', style: dim),
                cell('UI均', style: dim),
              ]),
              for (final (v, s) in r.rows)
                TableRow(children: [
                  cell('${v.code} ${v.label}', align: TextAlign.left),
                  cell(ms(s.rasterAvg)),
                  cell(ms(s.rasterP90)),
                  cell(ms(s.rasterMax)),
                  cell('${s.frames}'),
                  cell('${(s.overBudget * 100).round()}%'),
                  cell(s.fps == null ? '—' : hz(s.fps!)),
                  cell(ms(s.buildAvg)),
                ]),
            ],
          ),
          const SizedBox(height: Sp.x3),
          Text('单位 ms。fps = 帧数 / 实际时长。光栅 = FrameTiming.rasterDuration（GPU 线程），UI = buildDuration。截一张图发回即可。', style: dim),
        ],
      ]),
    );
  }
}

/// v3.5.4 顶部提示：系统不给高刷时让用户自己去系统设置里开（魅族 20 / Flyme 的具体菜单名未能确认，写通用说法）。
/// v3.5.5 只在 [perfNeedsHzHint] 时出现（真机已跑到 120Hz 时常驻这句会误导）。
const perfFlymeHint = 'Flyme 若仍 60Hz：到 系统设置 → 显示和亮度 里找“屏幕刷新率”选最高档；若有按应用设置刷新率的选项，给 Toyuis 选高刷';

/// v3.5.5 高刷提示的条件：滑动中采到的系统刷新率（所有变体合起来的最低值）低于 [perfHighHz]。
/// 读不到刷新率时不出：判断不了，不给可能误导的建议。
const perfHighHz = 90.0;
bool perfNeedsHzHint(PerfReport r) {
  final lo = [for (final (_, s) in r.rows) if (s.hzMin != null) s.hzMin!];
  return lo.isNotEmpty && lo.reduce((a, b) => a < b ? a : b) < perfHighHz;
}

/// “滑动中系统刷新率：最低 / 最高”（所有变体合起来）。
String perfHzLine(PerfReport r) {
  final lo = [for (final (_, s) in r.rows) if (s.hzMin != null) s.hzMin!];
  final hi = [for (final (_, s) in r.rows) if (s.hzMax != null) s.hzMax!];
  if (lo.isEmpty || hi.isEmpty) return '滑动中系统刷新率：读不到';
  String f(double v) => v.toStringAsFixed(1);
  return '滑动中系统刷新率：最低 ${f(lo.reduce((a, b) => a < b ? a : b))} Hz / 最高 ${f(hi.reduce((a, b) => a > b ? a : b))} Hz';
}

/// 结果页顶部的一块信息（小字逐行）。
class GlassCardInfo extends StatelessWidget {
  const GlassCardInfo({super.key, required this.lines});
  final List<String> lines;

  @override
  Widget build(BuildContext context) {
    final style = context.text.bodySmall!.copyWith(color: context.palette.text);
    return ListGroup(children: [
      Padding(
        padding: const EdgeInsets.symmetric(horizontal: Sp.x4, vertical: Sp.x2),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [for (final l in lines) Text(l, style: style)]),
      ),
    ]);
  }
}
