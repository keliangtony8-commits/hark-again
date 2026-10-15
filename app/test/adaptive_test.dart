// 自适应布局：断点分档、手机底部 Tab ↔ 平板侧边导航、聊天单栏 ↔ 双栏，以及切换时输入框内容不丢。
import 'package:assistant/core/api.dart';
import 'package:assistant/core/chat_socket.dart';
import 'package:assistant/features/chat/chat_scaffold.dart';
import 'package:assistant/features/chat/history_panel.dart';
import 'package:assistant/theme/app_theme.dart';
import 'package:assistant/theme/tokens.dart';
import 'package:assistant/shell/app_shell.dart' show shellBarShown;
import 'package:assistant/shell/top_bar.dart';
import 'package:assistant/ui/adaptive.dart';
import 'package:assistant/ui/motion.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'chat_controller_test.dart' show FakeSocket;

class _Api implements Api {
  @override
  Future<dynamic> get(String path) async => path.startsWith('/api/conversations') ? <dynamic>[] : null;
  @override
  dynamic noSuchMethod(Invocation i) => throw UnimplementedError();
}

void _size(WidgetTester tester, double w, [double h = 800]) {
  tester.view.physicalSize = Size(w, h);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
}

Widget _app(Widget home) => ProviderScope(
      overrides: [chatSocketProvider.overrideWithValue(FakeSocket()), apiProvider.overrideWithValue(_Api())],
      child: MaterialApp(theme: buildTheme(Brightness.light), home: home),
    );

const _tabs = <TopTab>[(label: '主页', badge: 3), (label: '聊天', badge: 0), (label: '项目', badge: 0)];

void main() {
  test('断点：<600 手机，600–839 中屏，≥840 双栏', () {
    expect(WindowSize.fromWidth(Layout.mediumMin - 1), WindowSize.compact);
    expect(WindowSize.fromWidth(Layout.mediumMin), WindowSize.medium);
    expect(WindowSize.fromWidth(Layout.expandedMin - 1).twoPane, isFalse);
    expect(WindowSize.fromWidth(Layout.expandedMin).twoPane, isTrue);
  });

  for (final w in [360.0, 700.0, 1100.0]) {
    testWidgets('浮动顶栏 $w 宽：三段 + 头像，分段不超宽，角标进读屏', (tester) async {
      _size(tester, w);
      final handle = tester.ensureSemantics();
      var picked = -1, me = 0;
      await tester.pumpWidget(_app(Scaffold(
        body: FloatingTopBar(tabs: _tabs, index: 0, onSelect: (i) => picked = i, onAvatar: () => me++),
      )));
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull);
      expect(tester.getSize(find.byType(SegmentedNav)).width, lessThanOrEqualTo(Layout.segmentsMax));
      expect(find.bySemanticsLabel('主页，3 条未读'), findsOneWidget);
      await tester.tap(find.text('聊天'));
      expect(picked, 1);
      await tester.tap(find.byTooltip('我的'));
      expect(me, 1);
      await expectLater(tester, meetsGuideline(androidTapTargetGuideline));
      handle.dispose();
    });
  }

  testWidgets('聊天：平板双栏常驻历史，转成手机宽变抽屉，输入框内容不丢', (tester) async {
    _size(tester, 1100);
    await tester.pumpWidget(_app(const ChatScaffold(title: Text('新对话'))));
    await tester.pumpAndSettle();
    expect(find.byWidgetPredicate((w) => w is HistoryPanel && w.docked), findsOneWidget);
    expect(find.byTooltip('历史'), findsNothing);

    // 专注模式：收起再展开，有过渡但不溢出
    await tester.tap(find.byTooltip('收起历史'));
    await tester.pump(Motion.fast);
    expect(tester.takeException(), isNull);
    await tester.pumpAndSettle();
    expect(find.byType(HistoryPanel), findsNothing);
    await tester.tap(find.byTooltip('展开历史'));
    await tester.pumpAndSettle();
    expect(find.byWidgetPredicate((w) => w is HistoryPanel && w.docked), findsOneWidget);

    await tester.enterText(find.byType(TextField).last, '写到一半');
    _size(tester, 400);
    await tester.pump(); // 尺寸变化那一帧就该是单栏，不能先挤压对话区
    expect(tester.takeException(), isNull);
    await tester.pumpAndSettle();
    expect(find.byType(HistoryPanel), findsNothing);
    expect(find.text('写到一半'), findsOneWidget);

    await tester.tap(find.byTooltip('历史'));
    await tester.pumpAndSettle();
    expect(find.byWidgetPredicate((w) => w is HistoryPanel && !w.docked), findsOneWidget);
    expect(find.byType(Drawer), findsOneWidget);
  });

  testWidgets('项目聊天（v2.93 §Q）：手机上左上 ≡ 在顶栏左槽；列表从 header 行下面滑出、≡ 变 +，点 + 新对话并收起', (tester) async {
    _size(tester, 400);
    await tester.pumpWidget(_app(ChatScaffold(
        projectId: 'p1', title: const Text('项目'), back: IconButton(icon: const Icon(Icons.chevron_left), tooltip: '返回项目列表', onPressed: () {}))));
    await tester.pumpAndSettle();
    final menu = find.byTooltip('项目对话');
    expect(menu, findsOneWidget);
    expect(tester.getTopLeft(menu).dx, Layout.gutter); // 顶栏左槽（与主聊天“历史”同位）
    expect(find.byType(BackButton), findsNothing); // 不再是子页面
    expect(find.byTooltip('返回项目列表'), findsOneWidget); // 返回在 header 行
    expect(tester.widget<MenuPlusIcon>(find.byType(MenuPlusIcon)).plus, isFalse);
    await tester.tap(menu);
    await tester.pumpAndSettle();
    final drawer = find.byType(Drawer);
    expect(drawer, findsOneWidget);
    expect(tester.getTopLeft(drawer).dx, 0); // 从左边出来
    // 左上钮仍在抽屉之上、可点：同一颗钮现在是 +
    expect(tester.widget<MenuPlusIcon>(find.byType(MenuPlusIcon)).plus, isTrue);
    expect(find.byTooltip('新对话'), findsOneWidget); // 手机项目抽屉里不再有第二个“新对话”钮
    await tester.tap(find.byTooltip('新对话'));
    await tester.pumpAndSettle();
    expect(find.byType(Drawer), findsNothing);
    expect(tester.widget<MenuPlusIcon>(find.byType(MenuPlusIcon)).plus, isFalse);
  });

  testWidgets('项目聊天：双栏时历史常驻、没有 ≡，左上是收起/展开', (tester) async {
    _size(tester, 1100);
    await tester.pumpWidget(_app(const ChatScaffold(projectId: 'p1', title: Text('项目'))));
    await tester.pumpAndSettle();
    expect(find.byType(MenuPlusIcon), findsNothing);
    expect(find.byWidgetPredicate((w) => w is HistoryPanel && w.docked), findsOneWidget);
    expect(tester.getTopLeft(find.byTooltip('收起项目对话')).dx, Layout.gutter);
    expect(find.byTooltip('新对话'), findsOneWidget); // 常驻栏保留自己的新对话
  });

  test('v2.93 shellBarShown：一级页面和项目页显示顶栏，项目的子页面不显示', () {
    for (final l in ['/home', '/chat', '/projects', '/projects/p1']) {
      expect(shellBarShown(l), isTrue, reason: l);
    }
    for (final l in ['/projects/p1/brief', '/projects/p1/computer', '/me', '/me/memory']) {
      expect(shellBarShown(l), isFalse, reason: l);
    }
  });
}
