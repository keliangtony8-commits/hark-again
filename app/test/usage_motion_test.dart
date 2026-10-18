// v0.71 用量页动效：骨架形状跟报表一致，加载完交叉淡化成报表；大数字从 0 滚到终值，结束时是原字符串；读屏只念终值。
import 'dart:async';

import 'package:assistant/core/cache.dart';
import 'package:assistant/core/api.dart';
import 'package:assistant/features/me/usage_screen.dart';
import 'package:assistant/theme/app_theme.dart';
import 'package:assistant/theme/tokens.dart';
import 'package:assistant/ui/motion.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

class SlowApi implements Api {
  final done = Completer<dynamic>();
  @override
  Future<dynamic> get(String path) => done.future;
  @override
  dynamic noSuchMethod(Invocation i) => throw UnimplementedError();
}

const body = {
  'currency': 'CNY',
  'budget': null,
  'priced': ['fast'],
  'today': {'calls': 3, 'tokens': 4200, 'cost': 1.5, 'models': []},
  'month': {'calls': 40, 'tokens': 2500000, 'cost': 12.0, 'models': []},
};

void main() {
  testWidgets('骨架 → 报表交叉淡化，数字滚到终值', (tester) async {
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    final api = SlowApi();
    await tester.pumpWidget(ProviderScope(
      overrides: [apiProvider.overrideWithValue(api), cacheStoreProvider.overrideWithValue(MemoryCacheStore())],
      child: MaterialApp(theme: buildTheme(Brightness.light), home: const UsageScreen()),
    ));
    await tester.pump();
    // 骨架：概览卡（月 + 今天 / 调用）+ 每日图，共 2 块
    expect(find.byType(Shimmer), findsNWidgets(2));
    expect(tester.getSize(find.byType(Shimmer).first).height, Layout.skeletonHero + Layout.skeletonStat);

    api.done.complete(body);
    await tester.pump();
    await tester.pump(Motion.base ~/ 2);
    // 交叉淡化中两态同时在树上
    expect(find.byType(Shimmer), findsWidgets);
    expect(find.byType(CountUp), findsWidgets);

    await tester.pumpAndSettle();
    expect(find.byType(Shimmer), findsNothing);
    expect(find.text('¥12.00'), findsOneWidget); // 滚完是原字符串
    expect(find.bySemanticsLabel('今天，¥1.50，3 次调用'), findsOneWidget);
  });
}
