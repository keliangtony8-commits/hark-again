// 用量与花费：解析与预算档位、格式化、我的页副标题、用量页三种状态（有预算/超预算/未定价）。
import 'package:assistant/core/cache.dart';
import 'package:assistant/core/api.dart';
import 'package:assistant/features/me/usage_screen.dart';
import 'package:assistant/models/usage.dart';
import 'package:assistant/theme/app_theme.dart';
import 'package:assistant/ui/format.dart';
import 'package:assistant/ui/motion.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

Map<String, dynamic> report({double? budget, List<String> priced = const ['fast'], double month = 12, double today = 1.5}) => {
      'currency': 'CNY',
      'budget': budget,
      'priced': priced,
      'today': {'calls': 3, 'tokens': 4200, 'cost': today, 'models': []},
      'month': {
        'calls': 40,
        'tokens': 2500000,
        'cost': month,
        'models': [
          {'model': 'fast', 'calls': 38, 'prompt_tokens': 2000000, 'completion_tokens': 480000, 'cached_tokens': 1240000, 'cost': month},
          {'model': 'embed', 'calls': 2, 'prompt_tokens': 20000, 'completion_tokens': 0, 'cost': 0},
        ],
      },
    };

class FakeApi implements Api {
  FakeApi(this.body);
  Map<String, dynamic> body;
  int calls = 0;

  @override
  Future<dynamic> get(String path) async {
    expect(path, '/api/usage');
    calls++;
    return body;
  }

  @override
  dynamic noSuchMethod(Invocation i) => throw UnimplementedError();
}

Future<void> pump(WidgetTester tester, FakeApi api) async {
  await tester.pumpWidget(ProviderScope(
    overrides: [apiProvider.overrideWithValue(api), cacheStoreProvider.overrideWithValue(MemoryCacheStore())],
    child: MaterialApp(theme: buildTheme(Brightness.light), home: const UsageScreen()),
  ));
  await tester.pumpAndSettle();
}

void main() {
  test('prompt cache hit label', () {
    expect(cacheHitLabel(0, 100), isNull);
    expect(cacheHitLabel(10, 0), isNull);
    expect(cacheHitLabel(62, 100), '缓存命中 62%');
    expect(cacheHitLabel(1, 1000), '缓存命中 <1%');
    expect(cacheHitLabel(200, 100), '缓存命中 100%');
    final r = UsageReport.fromJson(report());
    expect(r.month.models.first.cacheHit, '缓存命中 62%');
    expect(r.month.models.last.cacheHit, isNull); // 老服务器 / 没命中：不显示
    expect(UsagePeriod.fromJson({'prompt_tokens': 400, 'cached_tokens': 100}).cacheHit, '缓存命中 25%');
    expect(UsagePeriod.fromJson({'calls': 1}).cacheHit, isNull);
  });

  testWidgets('screen: model row shows the cache hit rate', (tester) async {
    await pump(tester, FakeApi(report(budget: 30)));
    expect(find.textContaining('缓存命中 62%'), findsOneWidget);
  });

  test('budget levels and unpriced detection', () {
    expect(UsageReport.fromJson(report()).budgetRatio, isNull);
    expect(UsageReport.fromJson(report()).level, BudgetLevel.ok);
    expect(UsageReport.fromJson(report(budget: 30)).level, BudgetLevel.ok);
    expect(UsageReport.fromJson(report(budget: 14)).level, BudgetLevel.near);
    expect(UsageReport.fromJson(report(budget: 10)).level, BudgetLevel.over);
    expect(UsageReport.fromJson(report()).hasUnpriced, true); // embed 没定价
    expect(UsageReport.fromJson(report(priced: ['fast', 'embed'])).hasUnpriced, false);
    final empty = UsageReport.fromJson({'currency': 'CNY'});
    expect(empty.month.calls, 0);
    expect(empty.month.models, isEmpty);
  });

  test('formatting', () {
    expect(formatMoney(12, 'CNY'), '¥12.00');
    expect(formatMoney(0.0123, 'CNY'), '¥0.012');
    expect(formatMoney(0, 'CNY'), '¥0.00');
    expect(formatMoney(3, 'USD'), r'$3.00');
    expect(formatTokens(999), '999');
    expect(formatTokens(4200), '4.2K');
    expect(formatTokens(48000), '48K');
    expect(formatTokens(2500000), '2.5M');
  });

  test('me row subtitle', () {
    expect(usageSubtitle(null), contains('token'));
    expect(usageSubtitle(UsageReport.fromJson(report(budget: 30))), '本月 ¥12.00 / 预算 ¥30.00');
    expect(usageSubtitle(UsageReport.fromJson(report())), '本月 ¥12.00');
    expect(usageSubtitle(UsageReport.fromJson(report(priced: []))), '本月 2.5M token');
  });

  testWidgets('screen: budget meter, per-model rows, unpriced hint', (tester) async {
    final api = FakeApi(report(budget: 30));
    await pump(tester, api);
    expect(find.text('¥12.00'), findsWidgets);
    expect(find.byKey(const Key('budget-meter')), findsOneWidget);
    expect(find.textContaining('还剩 ¥18.00（40%）'), findsOneWidget);
    expect(find.text('fast'), findsOneWidget);
    expect(find.text('未定价'), findsOneWidget);
    expect(find.textContaining('只统计 token'), findsOneWidget);
  });

  testWidgets('screen: over budget turns the meter danger-colored', (tester) async {
    await pump(tester, FakeApi(report(budget: 10)));
    expect(find.textContaining('已超出预算 ¥2.00'), findsOneWidget);
    final bar = tester.widget<MeterBar>(find.byKey(const Key('budget-meter')));
    expect(bar.color, tester.element(find.byType(Scaffold)).palette.danger);
  });

  testWidgets('screen: no prices → tokens only, no meter', (tester) async {
    await pump(tester, FakeApi(report(priced: [], budget: null)));
    expect(find.text('2.5M'), findsWidgets);
    expect(find.byKey(const Key('budget-meter')), findsNothing);
    expect(find.textContaining('MODEL_PRICES'), findsOneWidget);
  });

  testWidgets('screen: no daily from an old server → no chart', (tester) async {
    await pump(tester, FakeApi(report(budget: 30)));
    expect(find.text('本月每天'), findsNothing); // 老服务器
  });

  testWidgets('screen: daily chart shows up', (tester) async {
    await pump(tester, FakeApi({...report(budget: 30), 'daily': [{'date': '2026-10-01', 'calls': 1, 'tokens': 10, 'cost': 1.0}]}));
    expect(find.text('本月每天'), findsOneWidget);
    expect(find.byKey(const Key('usage-chart')), findsOneWidget);
  });

  testWidgets('pull to refresh refetches', (tester) async {
    final api = FakeApi(report(budget: 30));
    await pump(tester, api);
    api.body = report(budget: 30, month: 20);
    await tester.fling(find.byType(ListView), const Offset(0, 400), 1000);
    await tester.pumpAndSettle();
    expect(api.calls, 2);
    expect(find.text('¥20.00'), findsWidgets);
  });
}
