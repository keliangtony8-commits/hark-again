// 用量图选某天 → 那天明细（按模型 + 最花钱的对话）：今天也请求（途中先用报表的 today 画模型行）；点过去的某天请求那天；
// 对话行点开跳进对话（openConversation），已删的不可点；
// 拖动途中不请求、松手只请求最后那天；没调用的日子不显示也不请求；失败可点重试；下拉刷新作废缓存的明细。
import 'package:assistant/core/api.dart';
import 'package:assistant/features/me/usage_day.dart';
import 'package:assistant/features/me/usage_screen.dart';
import 'package:assistant/theme/app_theme.dart';
import 'package:assistant/ui/motion.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

Map<String, dynamic> m(String model, int p, int c, double cost, [int calls = 1]) =>
    {'model': model, 'calls': calls, 'prompt_tokens': p, 'completion_tokens': c, 'cost': cost};

final _report = {
  'currency': 'CNY',
  'budget': null,
  'priced': ['fast', 'smart'],
  'today': {'calls': 1, 'tokens': 500, 'cost': 0.5, 'models': [m('fast', 400, 100, 0.5)]},
  'month': {'calls': 4, 'tokens': 4500, 'cost': 4.5, 'models': []},
  'daily': [
    {'date': '2026-10-01', 'calls': 2, 'tokens': 3000, 'cost': 3.0},
    {'date': '2026-10-02', 'calls': 0, 'tokens': 0, 'cost': 0},
    {'date': '2026-10-03', 'calls': 1, 'tokens': 1000, 'cost': 1.0},
    {'date': '2026-10-04', 'calls': 1, 'tokens': 500, 'cost': 0.5},
  ],
};

class _Api implements Api {
  final days = <String>[];
  bool fail = false;
  @override
  Future<dynamic> get(String path) async {
    if (path == '/api/usage') return _report;
    if (path.startsWith('/api/usage/days/')) {
      final d = path.split('/').last;
      days.add(d);
      if (fail) throw ApiError('boom', 500);
      return {
        'currency': 'CNY',
        'priced': ['fast', 'smart'],
        'date': d,
        'total': {'calls': 2, 'tokens': 3000, 'cost': 3.0, 'models': [m('smart', 1000, 1000, 2.25), m('fast', 1000, 0, 0.75)]},
        'conversations': [
          {'id': 'c1', 'title': '写论文', 'calls': 1, 'tokens': 2000, 'cost': 2.25},
          {'id': 'gone', 'title': null, 'calls': 1, 'tokens': 1000, 'cost': 0.75},
        ],
      };
    }
    return null;
  }

  @override
  dynamic noSuchMethod(Invocation i) => throw UnimplementedError();
}

Future<Rect> _pump(WidgetTester tester, _Api api) async {
  tester.view.physicalSize = const Size(400, 1400);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(ProviderScope(
    overrides: [apiProvider.overrideWithValue(api)],
    child: MaterialApp(theme: buildTheme(Brightness.light), home: const UsageScreen()),
  ));
  await tester.pumpAndSettle();
  return tester.getRect(find.byKey(const Key('usage-chart')));
}

Offset _slot(Rect box, int i) => Offset(box.left + box.width / 31 * (i + 0.5), box.center.dy);

void main() {
  test('dayKey', () {
    expect(dayKey(DateTime(2026, 3, 7)), '2026-03-07');
  });

  testWidgets('默认今天：失败时仍用报表的 today 画模型行；成功后换成那天的明细和对话', (tester) async {
    final api = _Api()..fail = true;
    await _pump(tester, api);
    expect(api.days.toSet(), {'2026-10-04'});
    expect(find.byKey(const Key('day-model-fast')), findsOneWidget); // 报表 today 兜底
    expect(find.byKey(const Key('day-model-smart')), findsNothing);
    expect(find.text('明细加载失败，点这里重试'), findsOneWidget);
    expect(find.text('今天最花钱的对话'), findsNothing);
    api.fail = false;
    await tester.tap(find.text('明细加载失败，点这里重试'));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('day-model-smart')), findsOneWidget);
    expect(find.text('今天最花钱的对话'), findsOneWidget);
  });

  testWidgets('那天最花钱的对话：份额按当天算，点开跳对话，已删的不可点', (tester) async {
    final api = _Api();
    final box = await _pump(tester, api);
    await tester.tapAt(_slot(box, 0));
    await tester.pumpAndSettle();
    expect(find.text('那天最花钱的对话'), findsOneWidget);
    final bar = tester.widget<MeterBar>(find.descendant(of: find.byKey(const Key('day-conv-c1')), matching: find.byType(MeterBar)));
    expect(bar.value, closeTo(0.75, 1e-9));
    expect(find.textContaining('已删除的对话', findRichText: true), findsOneWidget);
    expect(find.descendant(of: find.byKey(const Key('day-conv-gone')), matching: find.byType(Pressable)), findsNothing);
    expect(find.descendant(of: find.byKey(const Key('day-conv-c1')), matching: find.byIcon(Icons.chevron_right_rounded)), findsOneWidget);
  });

  testWidgets('点过去某天：请求那天，按花费列出模型和占比', (tester) async {
    final api = _Api();
    final box = await _pump(tester, api);
    await tester.tapAt(_slot(box, 0));
    await tester.pumpAndSettle();
    expect(api.days, ['2026-10-04', '2026-10-01']);
    expect(find.byKey(const Key('day-model-smart')), findsOneWidget);
    expect(find.text('¥2.25'), findsNWidgets(2)); // 模型行 + 对话行
    final rows = tester.widgetList<DayModelRows>(find.byType(DayModelRows)).last;
    expect(rows.models.map((e) => e.model), ['smart', 'fast']);
    final bar = tester.widget<MeterBar>(find.descendant(of: find.byKey(const Key('day-model-smart')), matching: find.byType(MeterBar)));
    expect(bar.value, closeTo(0.75, 1e-9));

    await tester.tapAt(_slot(box, 1)); // 没调用的那天：不请求，不显示
    await tester.pumpAndSettle();
    expect(api.days, ['2026-10-04', '2026-10-01']);
    expect(find.byType(DayModelRows), findsNothing);
  });

  testWidgets('拖动途中不请求，松手只请求最后那天', (tester) async {
    final api = _Api();
    final box = await _pump(tester, api);
    final g = await tester.startGesture(_slot(box, 3));
    await g.moveBy(Offset(-box.width / 31, 0));
    await tester.pump();
    await g.moveBy(Offset(-box.width / 31, 0));
    await tester.pump();
    await g.moveBy(Offset(-box.width / 31, 0));
    await tester.pump();
    expect(find.text('10月1日'), findsOneWidget); // 读数跟手
    expect(api.days, ['2026-10-04']); // 只有进页时今天那一次
    await g.up();
    await tester.pumpAndSettle();
    expect(api.days, ['2026-10-04', '2026-10-01']);
  });

  testWidgets('失败可重试；下拉刷新作废明细', (tester) async {
    final api = _Api()..fail = true;
    final box = await _pump(tester, api);
    await tester.tapAt(_slot(box, 2));
    await tester.pumpAndSettle();
    expect(find.text('明细加载失败，点这里重试'), findsOneWidget);
    api.fail = false;
    await tester.tap(find.text('明细加载失败，点这里重试'));
    await tester.pumpAndSettle();
    expect(api.days.toSet(), {'2026-10-04', '2026-10-03'}); // Riverpod 自己也会退避重试几次，这里只看结果
    expect(find.byKey(const Key('day-model-smart')), findsOneWidget);

    final before = api.days.length;
    await tester.fling(find.byType(ListView).first, const Offset(0, 400), 1000);
    await tester.pumpAndSettle();
    expect(api.days.length, before + 1);
  });
}
