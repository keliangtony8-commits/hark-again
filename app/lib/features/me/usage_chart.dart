// 用量页“本月每天”：逐日柱状图。数据就是报表里的 daily（1 号到今天），只读、不另请求。
// 版面：上面一行是选中那天的读数（默认今天），下面按整月排格子（今天之后空着），底下标 1 日 / 中旬 / 月末。
// 有预算且定了价时画一条“日均预算”虚线，超过它的那天柱子用警示色——一眼看出哪天花多了。
// 交互：点或横向拖动选天；读屏把整张图当一个可调节的控件，上下滑动换天。
// 明细：[detail] 给了就在图下面挂“那天按模型”（usage_day.dart）。读数跟手变，明细只在选定时换
// （点下、拖完、读屏调节），拖动途中不触发请求。
// 动效：柱子用 motion.dart 的 GrowIn 一起长出来；颜色只取 Palette，尺寸只取 tokens。
import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../../models/usage.dart';
import '../../theme/app_theme.dart';
import '../../theme/tokens.dart';
import '../../ui/format.dart';
import '../../ui/motion.dart';

/// 一天的读数：“10月5日（今天）”+“¥1.23 · 40K token · 12 次”。没定价时只说 token。
String dayLabel(UsageDay d, {required bool today}) => '${d.date.month}月${d.date.day}日${today ? '（今天）' : ''}';

String dayValue(UsageDay d, UsageReport r) {
  if (d.calls == 0) return '没有调用';
  final tokens = '${formatTokens(d.tokens)} token · ${d.calls} 次';
  return r.priced.isEmpty ? tokens : '${formatMoney(d.cost, r.currency)} · $tokens';
}

class DailyUsageChart extends StatefulWidget {
  const DailyUsageChart({super.key, required this.report, this.detail});
  final UsageReport report;

  /// 选定那天的明细（day, 是否今天）；null = 不显示。
  final Widget Function(UsageDay day, bool today)? detail;

  @override
  State<DailyUsageChart> createState() => _DailyUsageChartState();
}

class _DailyUsageChartState extends State<DailyUsageChart> {
  int? _picked; // null = 跟着“今天”（最后一天），刷新后新的一天自动选中
  int? _settled; // 明细跟着的那天；拖动途中不变，松手才追上 _picked

  List<UsageDay> get _days => widget.report.daily;
  int get _selected => (_picked ?? _days.length - 1).clamp(0, _days.length - 1);
  int get _detailIndex => (_settled ?? _days.length - 1).clamp(0, _days.length - 1);
  bool get _money => widget.report.priced.isNotEmpty;
  double _value(UsageDay d) => _money ? d.cost : d.tokens.toDouble();

  void _pick(int i, {bool settle = true}) {
    final next = i.clamp(0, _days.length - 1);
    if (next == _selected && (!settle || _picked == _settled)) return;
    setState(() {
      _picked = next;
      if (settle) _settled = next;
    });
  }

  void _settle() {
    if (_settled != _picked) setState(() => _settled = _picked);
  }

  void _pickAt(Offset local, double width, {bool settle = true}) {
    final slots = widget.report.daysInMonth;
    if (width <= 0 || slots == 0) return;
    _pick((local.dx / width * slots).floor(), settle: settle);
  }

  /// 读屏念的那一天（当前值，以及上下滑动后会变成的值）。
  String _spoken(int i) => '${dayLabel(_days[i], today: i == _days.length - 1)}：${dayValue(_days[i], widget.report)}';

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final r = widget.report;
    final day = _days[_selected];
    final last = _selected == _days.length - 1;
    final pace = r.dailyPace;
    final peak = _days.reduce((a, b) => _value(b) > _value(a) ? b : a);
    final slots = r.daysInMonth;

    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Row(crossAxisAlignment: CrossAxisAlignment.baseline, textBaseline: TextBaseline.alphabetic, children: [
        Text(dayLabel(day, today: last), style: context.text.labelSmall),
        const SizedBox(width: Sp.x2),
        Expanded(
          child: SwapSwitcher(
            child: Text(dayValue(day, r),
                key: ValueKey(_selected), style: context.text.titleSmall?.copyWith(color: p.text)),
          ),
        ),
      ]),
      const SizedBox(height: Sp.x3),
      Semantics(
        label: '本月每天的${_money ? '花费' : 'token'}，最多的是 ${peak.date.day} 日（${dayValue(peak, r)}）',
        value: _spoken(_selected),
        increasedValue: _selected < _days.length - 1 ? _spoken(_selected + 1) : null,
        decreasedValue: _selected > 0 ? _spoken(_selected - 1) : null,
        onIncrease: _selected < _days.length - 1 ? () => _pick(_selected + 1) : null,
        onDecrease: _selected > 0 ? () => _pick(_selected - 1) : null,
        excludeSemantics: true,
        child: LayoutBuilder(
          builder: (context, box) => GestureDetector(
            key: const Key('usage-chart'),
            behavior: HitTestBehavior.opaque,
            onTapDown: (e) => _pickAt(e.localPosition, box.maxWidth),
            onHorizontalDragUpdate: (e) => _pickAt(e.localPosition, box.maxWidth, settle: false),
            onHorizontalDragEnd: (_) => _settle(),
            onHorizontalDragCancel: _settle,
            child: GrowIn(
              builder: (_, t) => CustomPaint(
                size: Size(box.maxWidth, Layout.chartHeight),
                painter: DailyBarsPainter(
                  values: [for (final d in _days) _value(d)],
                  slots: slots,
                  selected: _selected,
                  pace: _money ? pace : null,
                  progress: t,
                  bar: p.ink,
                  over: p.warning,
                  guide: p.border,
                  paceColor: p.warning,
                ),
              ),
            ),
          ),
        ),
      ),
      const SizedBox(height: Sp.x1),
      ExcludeSemantics(
        child: Row(children: [
          Text('1日', style: context.text.bodySmall),
          const Spacer(),
          Text('${(slots / 2).ceil()}日', style: context.text.bodySmall),
          const Spacer(),
          Text('$slots日', style: context.text.bodySmall),
        ]),
      ),
      if (pace != null && _money) ...[
        const SizedBox(height: Sp.x2),
        Row(children: [
          CustomPaint(size: const Size(Sp.x4, Sp.x2), painter: _DashPainter(p.warning)),
          const SizedBox(width: Sp.x2),
          Text('日均预算 ${formatMoney(pace, r.currency)}，超过的那天标成橙色', style: context.text.bodySmall),
        ]),
      ],
      if (widget.detail != null)
        SwapSwitcher(
          child: KeyedSubtree(
            key: ValueKey(_days[_detailIndex].date),
            child: widget.detail!(_days[_detailIndex], _detailIndex == _days.length - 1),
          ),
        ),
    ]);
  }
}

/// 柱子 + 底线 + 日均预算虚线。values 只有到今天为止的天数，slots 是整月格子数。
/// 选中的柱子满色，其他半透明；超过 pace 的用 over 色。progress 0~1 控制柱高（入场动画）。
class DailyBarsPainter extends CustomPainter {
  DailyBarsPainter({
    required this.values,
    required this.slots,
    required this.selected,
    required this.pace,
    required this.progress,
    required this.bar,
    required this.over,
    required this.guide,
    required this.paceColor,
  });

  final List<double> values;
  final int slots, selected;
  final double? pace;
  final double progress;
  final Color bar, over, guide, paceColor;

  static const _gapRatio = 0.28; // 柱间空隙占格子宽的比例
  static const _headroom = 1.12; // 最高的柱子不顶天
  static const _minVisible = 2.0; // 有用量但很小的那天至少露一点头

  /// 纵轴上限：最高的一天和预算虚线取大，再留一点头。全是 0 时给 1，避免除零。
  double get top {
    final peak = values.fold<double>(0, math.max);
    final m = math.max(peak, pace ?? 0) * _headroom;
    return m > 0 ? m : 1;
  }

  @override
  void paint(Canvas canvas, Size size) {
    if (slots == 0) return;
    final h = size.height;
    final slot = size.width / slots;
    final w = math.max(slot * (1 - _gapRatio), 1.0);
    final radius = Radius.circular(math.min(w / 2, Radii.inner / 2));
    canvas.drawLine(Offset(0, h - 0.5), Offset(size.width, h - 0.5), Paint()..color = guide);

    for (var i = 0; i < values.length && i < slots; i++) {
      final v = values[i];
      if (v <= 0) continue;
      final bh = math.max(v / top * h, _minVisible) * progress;
      final x = i * slot + (slot - w) / 2;
      final hot = pace != null && v > pace!;
      final color = (hot ? over : bar).withValues(alpha: i == selected ? 1 : 0.42);
      canvas.drawRRect(RRect.fromRectAndCorners(Rect.fromLTWH(x, h - bh, w, bh), topLeft: radius, topRight: radius), Paint()..color = color);
    }

    // 选中的那天如果是 0，也画一个小点告诉用户选中了哪里
    if (selected < values.length && values[selected] <= 0) {
      canvas.drawCircle(Offset(selected * slot + slot / 2, h - Sp.x1), math.min(w / 2, Sp.x1 / 2 + 1), Paint()..color = bar);
    }

    if (pace != null) {
      final y = h - pace! / top * h;
      final paint = Paint()
        ..color = paceColor.withValues(alpha: progress)
        ..strokeWidth = 1;
      for (double x = 0; x < size.width; x += Sp.x2) {
        canvas.drawLine(Offset(x, y), Offset(math.min(x + Sp.x1, size.width), y), paint);
      }
    }
  }

  @override
  bool shouldRepaint(DailyBarsPainter old) =>
      old.progress != progress ||
      old.selected != selected ||
      old.slots != slots ||
      old.pace != pace ||
      old.bar != bar ||
      old.over != over ||
      old.guide != guide ||
      !_same(old.values, values);

  static bool _same(List<double> a, List<double> b) {
    if (a.length != b.length) return false;
    for (var i = 0; i < a.length; i++) {
      if (a[i] != b[i]) return false;
    }
    return true;
  }
}

/// 图例里那一小段虚线。
class _DashPainter extends CustomPainter {
  _DashPainter(this.color);
  final Color color;

  @override
  void paint(Canvas canvas, Size size) {
    final y = size.height / 2;
    final paint = Paint()
      ..color = color
      ..strokeWidth = 1;
    for (double x = 0; x < size.width; x += Sp.x2) {
      canvas.drawLine(Offset(x, y), Offset(math.min(x + Sp.x1, size.width), y), paint);
    }
  }

  @override
  bool shouldRepaint(_DashPainter old) => old.color != color;
}
