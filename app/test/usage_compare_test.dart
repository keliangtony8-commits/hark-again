// 上月对比：解析 last_month、涨跌口径（有定价按钱，否则 token）、基数为 0 / 老服务器的退化、月卡上的标签与读屏文字。
import 'package:assistant/core/api.dart';
import 'package:assistant/features/me/usage_screen.dart';
import 'package:assistant/models/usage.dart';
import 'package:assistant/theme/app_theme.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

Map<String, dynamic> report({List<String> priced = const ['fast'], double month = 12, int tokens = 2000000, Map<String, dynamic>? last}) => {
      'currency': 'CNY',
      'budget': null,
      'priced': priced,
      'today': {'calls': 1, 'tokens': 10, 'cost': 0.1, 'models': []},
      'month': {'calls': 40, 'tokens': tokens, 'cost': month, 'models': []},
      'last_month': ?last,
    };

Map<String, dynamic> last({double cost = 30, int tokens = 4000000, double toCost = 10, int toTokens = 1000000}) => {
      'calls': 90, 'tokens': tokens, 'cost': cost,
      'to_date': {'calls': 30, 'tokens': toTokens, 'cost': toCost},
    };

class FakeApi implements Api {
  FakeApi(this.body);
  final Map<String, dynamic> body;
  @override
  Future<dynamic> get(String path) async => body;
  @override
  dynamic noSuchMethod(Invocation i) => throw UnimplementedError();
}

Future<void> pump(WidgetTester tester, Map<String, dynamic> body) async {
  await tester.pumpWidget(const SizedBox()); // 换一份数据：先卸掉旧的 ProviderScope
  await tester.pumpWidget(ProviderScope(
    overrides: [apiProvider.overrideWithValue(FakeApi(body))],
    child: MaterialApp(theme: buildTheme(Brightness.light), home: const UsageScreen()),
  ));
  await tester.pumpAndSettle();
}

void main() {
  test('delta uses money when priced, tokens otherwise', () {
    final r = UsageReport.fromJson(report(last: last()));
    expect(r.lastMonth!.total.cost, 30);
    expect(r.lastMonth!.toDate.tokens, 1000000);
    expect(r.monthDelta, closeTo(0.2, 1e-9)); // 12 vs 10
    final t = UsageReport.fromJson(report(priced: [], last: last()));
    expect(t.monthDelta, closeTo(1.0, 1e-9)); // 2M vs 1M token
  });

  test('no base → null delta; old server → no lastMonth', () {
    expect(UsageReport.fromJson(report(last: last(toCost: 0))).monthDelta, isNull);
    final old = UsageReport.fromJson(report());
    expect(old.lastMonth, isNull);
    expect(old.monthDelta, isNull);
  });

  testWidgets('month card shows rise with semantics label', (tester) async {
    final handle = tester.ensureSemantics();
    await pump(tester, report(last: last()));
    expect(find.byKey(const Key('month-delta')), findsOneWidget);
    expect(find.text('+20%'), findsOneWidget);
    expect(find.text('· 上月全月 ¥30.00'), findsOneWidget);
    expect(find.bySemanticsLabel('比上月同期多 20%'), findsOneWidget);
    handle.dispose();
  });

  testWidgets('drop, flat and huge rise', (tester) async {
    final handle = tester.ensureSemantics();
    await pump(tester, report(month: 5, last: last()));
    expect(find.text('−50%'), findsOneWidget);
    await pump(tester, report(month: 10.2, last: last()));
    expect(find.text('持平'), findsOneWidget);
    expect(find.bySemanticsLabel('与上月同期持平'), findsOneWidget);
    await pump(tester, report(month: 300, last: last()));
    expect(find.text('+30 倍'), findsOneWidget);
    handle.dispose();
  });

  testWidgets('no base explains instead; old server shows nothing', (tester) async {
    await pump(tester, report(last: last(toCost: 0)));
    expect(find.byKey(const Key('month-delta')), findsNothing);
    expect(find.text('上月同期没有用量 · 上月全月 ¥30.00'), findsOneWidget);
    await pump(tester, report(last: last(cost: 0, toCost: 0, tokens: 0, toTokens: 0)));
    expect(find.text('上月没有用量'), findsOneWidget);
    await pump(tester, report());
    expect(find.textContaining('上月'), findsNothing);
  });
}
