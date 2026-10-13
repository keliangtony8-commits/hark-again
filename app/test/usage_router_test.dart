// 用量页“自动选模型”：解析（老服务器 / 没用过 → null）、文案（约省 / 多花 / 没定价给轮数）、分类器一行、说明；
// 界面：报表有 router 才出这一节，大数字、两档占比、亏了换成提醒色说明。
import 'package:assistant/core/api.dart';
import 'package:assistant/features/me/usage_screen.dart';
import 'package:assistant/models/usage.dart';
import 'package:assistant/theme/app_theme.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

Map<String, dynamic> _router({double? saved = 0.012, double? net = 0.0092}) => {
      'turns': 4, 'simple': 3, 'complex': 1, 'free': 2,
      'classifier': {'turns': 2, 'cost': 0.0028, 'ms': 140},
      'simple_cost': 0.012, 'saved': saved, 'net': net, 'simple_model': '快速', 'complex_model': '深度',
    };

Map<String, dynamic> _report({Map<String, dynamic>? router}) => {
      'currency': 'CNY',
      'budget': null,
      'priced': ['fast', 'smart'],
      'today': {'calls': 1, 'tokens': 100, 'cost': 0.01, 'models': []},
      'month': {'calls': 10, 'tokens': 1000, 'cost': 1, 'models': []},
      'router': ?router,
    };

class _Api implements Api {
  _Api(this.body);
  final Map<String, dynamic> body;
  @override
  Future<dynamic> get(String path) async => path == '/api/usage' ? body : null;
  @override
  dynamic noSuchMethod(Invocation i) => throw UnimplementedError();
}

Future<void> _pump(WidgetTester tester, Map<String, dynamic> body) async {
  await tester.pumpWidget(ProviderScope(
    overrides: [apiProvider.overrideWithValue(_Api(body))],
    child: MaterialApp(theme: buildTheme(Brightness.light), home: const UsageScreen()),
  ));
  await tester.pumpAndSettle();
}

void main() {
  test('解析与文案', () {
    expect(UsageReport.fromJson(_report()).router, isNull); // 老服务器 / 本月没用过“自动”
    final u = UsageReport.fromJson(_report(router: _router())).router!;
    expect((u.turns, u.simple, u.complex, u.free, u.classifierTurns, u.classifierMs), (4, 3, 1, 2, 2, 140));
    expect(u.simpleShare, 0.75);
    expect(u.losing, false);
    expect(routerHeadline(u, 'CNY'), '约省 ¥0.009');
    expect(routerSplitLine(u), '本月 4 轮 · 快速 3 轮 · 深度 1 轮');
    expect(routerCostLine(u, 'CNY', money: true), '2 轮按规则直接定（不花钱） · 2 轮问了分类器，花 ¥0.003，平均 140 毫秒');
    expect(routerCostLine(u, 'CNY', money: false), '2 轮按规则直接定（不花钱） · 2 轮问了分类器，平均 140 毫秒');
    expect(routerNote(u), contains('估算'));

    final lose = RouterUsage.fromJson(_router(net: -0.002));
    expect(lose.losing, true);
    expect(routerHeadline(lose, 'CNY'), '多花 ¥0.002');
    expect(routerNote(lose), contains('rules'));

    final unpriced = RouterUsage.fromJson(_router(saved: null, net: null));
    expect(routerHeadline(unpriced, 'CNY'), '4 轮');
    expect(routerNote(unpriced), contains('MODEL_PRICES'));

    const none = RouterUsage(turns: 0);
    expect(none.simpleShare, 0);
    expect(routerCostLine(none, 'CNY', money: true), '都用了默认档');
    expect(routerSplitLine(none), '本月 0 轮 · 简单档 0 轮 · 复杂档 0 轮');
  });

  testWidgets('没有 router 不出这一节', (tester) async {
    await _pump(tester, _report());
    expect(find.byKey(const Key('router-usage')), findsNothing);
  });

  testWidgets('有 router：大数字、占比、说明', (tester) async {
    await _pump(tester, _report(router: _router(net: -0.002)));
    await tester.scrollUntilVisible(find.byKey(const Key('router-usage')), 200);
    await tester.pumpAndSettle();
    expect(find.text('自动选模型'), findsWidgets);
    expect(find.text('多花 ¥0.002'), findsOneWidget);
    expect(find.text('快速 75%'), findsOneWidget);
    expect(find.text('深度 25%'), findsOneWidget);
    final note = tester.widget<Text>(find.byKey(const Key('router-note')));
    expect(note.data, contains('rules'));
    expect(find.bySemanticsLabel(RegExp('自动选模型，多花')), findsOneWidget);
  });
}
