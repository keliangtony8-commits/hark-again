// v3.5.1 我的电脑一屏概览（用户 10-18 真机截图：原来约 4.7 屏长、内存 / 服务重复出现）：
// 主页一屏内放下状态卡 + 后台任务前 3 行 + 单行导航；“全部 N 个 ›”和每个导航行进 /me/computer/:part 子页（子页不重复节标题）；
// “重启”在标题行右侧的玻璃圆钮，确认后才 POST。
import 'package:assistant/core/api.dart';
import 'package:assistant/core/cache.dart';
import 'package:assistant/features/computer/computer_screen.dart';
import 'package:assistant/theme/app_theme.dart';
import 'package:assistant/ui/glass.dart';
import 'package:assistant/ui/kit.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';

import 'support/computer_usage_fixture.dart';

class _Api implements Api {
  _Api(this.status);
  Map<String, dynamic> status;
  final calls = <String>[];

  @override
  Future<dynamic> get(String path) async {
    calls.add('GET $path');
    if (path == '/api/browser/sessions') return browserSessionsFixture();
    if (path == '/api/host') return hostFixture();
    return status;
  }

  @override
  Future<dynamic> post(String path, [Object? body]) async {
    calls.add('POST $path');
    status = {...status, 'running_jobs': <dynamic>[], 'services': <dynamic>[]};
    return status;
  }

  @override
  dynamic noSuchMethod(Invocation i) => throw UnimplementedError();
}

/// 截图同量级 + 3 个普通后台任务（一共 5 行，主页只露 3 行）。
Map<String, dynamic> _busy() => {
      ...computerFixture(),
      'running_jobs': [
        for (final (i, t) in ['训练模型', '抓取价格', '生成报表'].indexed)
          {'id': 'j$i', 'title': t, 'command': 'python job$i.py', 'state': 'running', 'elapsed': 60 + i, 'tail': ''},
      ],
    };

Future<void> _settle(WidgetTester tester) async {
  for (var i = 0; i < 12; i++) {
    await tester.pump(const Duration(milliseconds: 100));
  }
}

Future<_Api> _pump(WidgetTester tester, Map<String, dynamic> status) async {
  tester.view.physicalSize = const Size(412, 915);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  final api = _Api(status);
  final router = GoRouter(initialLocation: '/me/computer', routes: [
    GoRoute(path: '/me', builder: (_, _) => const SizedBox(), routes: [
      GoRoute(path: 'computer', builder: (_, _) => const ComputerScreen(), routes: [
        GoRoute(path: ':part', builder: (_, s) => ComputerDetailScreen(part: s.pathParameters['part']!)),
      ]),
      GoRoute(path: 'pages', builder: (_, _) => const Scaffold(body: Text('Pages 页'))),
    ]),
  ]);
  await tester.pumpWidget(ProviderScope(
    overrides: [apiProvider.overrideWithValue(api), cacheStoreProvider.overrideWithValue(MemoryCacheStore())],
    child: MaterialApp.router(theme: buildTheme(Brightness.dark), routerConfig: router),
  ));
  await _settle(tester);
  return api;
}

void main() {
  testWidgets('主页一屏：状态卡、后台任务前 3 行、导航行都在屏内，不再平铺各节', (tester) async {
    await _pump(tester, _busy());
    expect(find.text('运行中'), findsOneWidget);
    // 后台任务只露前 3 行（服务排前面）
    expect(find.text('启动库存监控网页服务'), findsOneWidget);
    expect(find.text('训练模型'), findsOneWidget);
    expect(find.text('抓取价格'), findsNothing);
    expect(find.text('全部 5 个 ›'), findsOneWidget);
    // 导航行 + 行尾值
    for (final k in ['ports', 'memory', 'processes', 'disk', 'browser', 'pages', 'host']) {
      expect(find.byKey(Key('computer-nav-$k')), findsOneWidget, reason: k);
    }
    expect(tester.getRect(find.byKey(const Key('computer-nav-ports'))).bottom, lessThanOrEqualTo(915), reason: '导航从第一屏开始');
    expect(find.text('3 个'), findsOneWidget); // 端口
    expect(find.text('8 个'), findsOneWidget); // 程序
    expect(find.text('3 个网站'), findsOneWidget);
    expect(find.text('关闭'), findsOneWidget); // 主机模式
    // 原来平铺的节不在主页上（内存 / 端口不再重复出现）
    expect(find.text('端口 5000'), findsNothing);
    expect(find.text('正在监听的端口'), findsNothing);
    expect(find.text('最近 7 天谁写得最多'), findsNothing);
    // 设置搜索的定位点还在主页（导航行）
    expect(find.byType(Spotlight), findsNWidgets(3));
  });

  testWidgets('截图同量级（2 个服务、没有普通任务）：整页约一屏，导航行全在第一屏', (tester) async {
    await _pump(tester, computerFixture());
    expect(find.text('全部 2 个 ›'), findsNothing);
    for (final k in ['ports', 'memory', 'processes', 'disk', 'browser', 'pages', 'host']) {
      expect(tester.getRect(find.byKey(Key('computer-nav-$k'))).bottom, lessThanOrEqualTo(915), reason: '$k 要在第一屏里');
    }
    final pos = tester.state<ScrollableState>(find.byType(Scrollable).first).position;
    expect(pos.maxScrollExtent, lessThan(200), reason: '原来约 3500px，现在只剩页底小字');
    expect(find.byKey(const Key('computer-intro')), findsOneWidget); // 原页头说明挪到页底一行小字
  });

  testWidgets('全部 › 进后台任务子页（全量）；导航行进子页，子页不重复节标题', (tester) async {
    await _pump(tester, _busy());
    await tester.tap(find.text('全部 5 个 ›'));
    await _settle(tester);
    expect(find.text('后台任务'), findsOneWidget); // 页标题
    for (final t in ['启动库存监控网页服务', '训练模型', '抓取价格', '生成报表']) {
      expect(find.text(t), findsOneWidget, reason: t);
    }
    Navigator.of(tester.element(find.text('生成报表'))).pop();
    await _settle(tester);

    await tester.tap(find.byKey(const Key('computer-nav-ports')));
    await _settle(tester);
    expect(find.text('端口 5000'), findsOneWidget);
    expect(find.text('正在监听的端口'), findsOneWidget); // 页标题，没有第二个节标题
    Navigator.of(tester.element(find.text('端口 5000'))).pop();
    await _settle(tester);

    await tester.tap(find.byKey(const Key('computer-nav-disk')));
    await _settle(tester);
    expect(find.text('磁盘'), findsOneWidget);
    expect(find.text('装过的工具'), findsOneWidget);
    expect(find.text('最近 7 天谁写得最多'), findsOneWidget);
  });

  testWidgets('磁盘紧张 / 已满：导航行的值变色', (tester) async {
    await _pump(tester, {...computerFixture(), 'disk_used': 3 << 30, 'disk_level': 'full'});
    final v = tester.widget<Text>(find.descendant(of: find.byKey(const Key('computer-nav-disk')), matching: find.textContaining(' / 3 GB')));
    final p = tester.element(find.byKey(const Key('computer-nav-disk'))).palette;
    expect(v.style?.color, p.danger);
  });

  testWidgets('重启：标题行右侧圆钮，先确认，确认后 POST restart', (tester) async {
    final api = await _pump(tester, _busy());
    expect(find.text('重启这台电脑？'), findsNothing);
    await tester.tap(find.byTooltip('重启'));
    await _settle(tester);
    expect(find.text('重启这台电脑？'), findsOneWidget);
    expect(find.textContaining('将停止 3 个'), findsOneWidget);
    expect(api.calls.where((c) => c.startsWith('POST')), isEmpty);
    await tester.tap(find.descendant(of: find.byType(PillButton), matching: find.text('重启')));
    await _settle(tester);
    expect(api.calls, contains('POST /api/projects/me/computer/restart'));
    expect(find.text('训练模型'), findsNothing);
    await tester.pump(const Duration(seconds: 4)); // 吐司走完
  });
}
