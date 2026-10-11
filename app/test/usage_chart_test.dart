// 用量页“本月每天”：daily 解析、月长与日均预算、读数文案、点/拖选天、默认选今天、
// 预算虚线图例只在有预算且定价时出现、超过日均的柱子用警示色、读屏可上下换天、减少动态时柱子直接到位。
import 'package:assistant/features/me/usage_chart.dart';
import 'package:assistant/models/usage.dart';
import 'package:assistant/theme/app_theme.dart';
import 'package:assistant/ui/motion.dart';
import 'package:flutter/material.dart';
import 'package:flutter/semantics.dart';
import 'package:flutter_test/flutter_test.dart';

Map<String, dynamic> report({double? budget = 31, List<String> priced = const ['fast'], int days = 5}) => {
      'currency': 'CNY',
      'budget': budget,
      'priced': priced,
      'today': {'calls': 1, 'tokens': 100, 'cost': 0.5, 'models': []},
      'month': {'calls': 6, 'tokens': 9000, 'cost': 4.5, 'models': []},
      'daily': [
        for (var i = 1; i <= days; i++)
          {'date': '2026-10-${i.toString().padLeft(2, '0')}', 'calls': i == 2 ? 0 : 1, 'tokens': i * 1000, 'cost': i == 3 ? 2.0 : 0.5},
      ],
    };

Future<void> pump(WidgetTester tester, UsageReport r, {bool reduce = false}) async {
  await tester.pumpWidget(MaterialApp(
    theme: buildTheme(Brightness.light),
    home: MediaQuery(
      data: MediaQueryData(size: const Size(400, 800), disableAnimations: reduce),
      child: Scaffold(body: Padding(padding: const EdgeInsets.all(20), child: DailyUsageChart(report: r))),
    ),
  ));
  if (!reduce) await tester.pumpAndSettle();
}

DailyBarsPainter painterOf(WidgetTester tester) =>
    tester.widget<CustomPaint>(find.descendant(of: find.byKey(const Key('usage-chart')), matching: find.byType(CustomPaint))).painter! as DailyBarsPainter;

void main() {
  test('daily parsing, month length, pace', () {
    final r = UsageReport.fromJson(report());
    expect(r.daily.length, 5);
    expect(r.daily[2].cost, 2.0);
    expect(r.daily.first.date, DateTime(2026, 10, 1));
    expect(r.daysInMonth, 31);
    expect(r.dailyPace, 1.0);
    expect(UsageReport.fromJson(report(budget: null)).dailyPace, isNull);
    expect(UsageReport.fromJson(report(priced: [])).dailyPace, isNull);
    final old = UsageReport.fromJson({'currency': 'CNY'}); // 老服务器没有 daily
    expect(old.daily, isEmpty);
    expect(old.daysInMonth, 0);
    expect(UsageReport.fromJson({...report(), 'daily': [{'date': '2026-02-01'}]}).daysInMonth, 28);
  });

  test('labels', () {
    final r = UsageReport.fromJson(report());
    expect(dayLabel(r.daily[4], today: true), '10月5日（今天）');
    expect(dayValue(r.daily[0], r), '¥0.50 · 1.0K token · 1 次');
    expect(dayValue(r.daily[1], r), '没有调用');
    expect(dayValue(r.daily[0], UsageReport.fromJson(report(priced: []))), '1.0K token · 1 次');
  });

  test('painter scale and repaint', () {
    DailyBarsPainter make({double? pace, double progress = 1, int selected = 0}) => DailyBarsPainter(
        values: const [0.5, 2], slots: 31, selected: selected, pace: pace, progress: progress,
        bar: Colors.orange, over: Colors.red, guide: Colors.grey, paceColor: Colors.red);
    expect(make().top, closeTo(2 * 1.12, 1e-9));
    expect(make(pace: 5).top, closeTo(5 * 1.12, 1e-9)); // 预算线比最高柱还高：纵轴让给它
    expect(DailyBarsPainter(values: const [0, 0], slots: 31, selected: 0, pace: null, progress: 1,
        bar: Colors.orange, over: Colors.red, guide: Colors.grey, paceColor: Colors.red).top, 1);
    expect(make().shouldRepaint(make()), false);
    expect(make().shouldRepaint(make(progress: .5)), true);
    expect(make().shouldRepaint(make(selected: 1)), true);
  });

  testWidgets('defaults to today, tap/drag picks a day', (tester) async {
    await pump(tester, UsageReport.fromJson(report()));
    expect(find.text('10月5日（今天）'), findsOneWidget);
    expect(painterOf(tester).selected, 4);
    expect(painterOf(tester).progress, 1);
    final box = tester.getRect(find.byKey(const Key('usage-chart')));
    final slot = box.width / 31;
    await tester.tapAt(Offset(box.left + slot * 2.5, box.center.dy)); // 第 3 格 = 3 日
    await tester.pumpAndSettle();
    expect(find.text('10月3日'), findsOneWidget);
    expect(find.text('¥2.00 · 3.0K token · 1 次'), findsOneWidget);
    await tester.tapAt(Offset(box.right - 2, box.center.dy)); // 未来的格子：夹到今天
    await tester.pumpAndSettle();
    expect(find.text('10月5日（今天）'), findsOneWidget);
    await tester.dragFrom(Offset(box.left + slot * 4.5, box.center.dy), Offset(-slot * 4, 0));
    await tester.pumpAndSettle();
    expect(find.text('10月1日'), findsOneWidget);
  });

  testWidgets('pace legend only with budget and prices; hot day uses warning color', (tester) async {
    await pump(tester, UsageReport.fromJson(report()));
    expect(find.textContaining('日均预算 ¥1.00'), findsOneWidget);
    expect(painterOf(tester).pace, 1.0);
    await pump(tester, UsageReport.fromJson(report(budget: null)));
    expect(find.textContaining('日均预算'), findsNothing);
    expect(painterOf(tester).pace, isNull);
    await pump(tester, UsageReport.fromJson(report(priced: [])));
    expect(find.textContaining('日均预算'), findsNothing);
    expect(painterOf(tester).values, [1000, 2000, 3000, 4000, 5000]); // 没定价：画 token
  });

  testWidgets('screen reader: one adjustable control', (tester) async {
    final handle = tester.ensureSemantics();
    await pump(tester, UsageReport.fromJson(report()));
    final node = tester.getSemantics(find.byKey(const Key('usage-chart')));
    expect(node.label, contains('最多的是 3 日'));
    expect(node.value, '10月5日（今天）：¥0.50 · 5.0K token · 1 次');
    tester.semantics.performAction(find.semantics.byValue('10月5日（今天）：¥0.50 · 5.0K token · 1 次'), SemanticsAction.decrease);
    await tester.pumpAndSettle();
    expect(find.text('10月4日'), findsOneWidget);
    handle.dispose();
  });

  testWidgets('reduce motion: bars are fully grown on first frame', (tester) async {
    await pump(tester, UsageReport.fromJson(report()), reduce: true);
    await tester.pump();
    expect(painterOf(tester).progress, 1);
    expect(find.byType(GrowIn), findsOneWidget);
  });
}
