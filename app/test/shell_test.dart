// 设计 v2 外壳：浮动顶栏只在一级页面出现，进子页面淡出；头像进入“我的”（盖在外壳上，返回回到原处）；
// 深链直接落在 /me/… 时，“我的”的返回去主页而不是退出 App；一级页面的上下文按钮各就各位。
import 'dart:async';

import 'package:assistant/app.dart';
import 'package:assistant/core/api.dart';
import 'package:assistant/core/chat_socket.dart';
import 'package:assistant/core/session.dart';
import 'package:assistant/shell/top_bar.dart';
import 'package:assistant/ui/motion.dart';
import 'package:assistant/ui/sky.dart';
import 'package:flutter/material.dart';
import 'package:flutter/widgets.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'chat_controller_test.dart' show FakeSocket;

class _SignedIn extends SessionNotifier {
  @override
  Future<Session> build() async => const Session(server: 'http://x', token: 't');
}

class _Api implements Api {
  @override
  Future<dynamic> get(String path) async {
    if (path == '/api/inbox') return {'unread': 0, 'latest': null};
    if (path == '/api/projects') {
      return [
        {'id': 'p1', 'name': '考研', 'emoji': '📚', 'rules': ''}
      ];
    }
    return <dynamic>[];
  }

  @override
  dynamic noSuchMethod(Invocation i) => throw UnimplementedError();
}

Future<GoRouter> _pump(WidgetTester tester) async {
  tester.view.physicalSize = const Size(400, 860);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  SharedPreferences.setMockInitialValues({});
  final container = ProviderContainer(overrides: [
    sessionProvider.overrideWith(_SignedIn.new),
    apiProvider.overrideWithValue(_Api()),
    chatSocketProvider.overrideWithValue(FakeSocket()),
  ]);
  addTearDown(container.dispose);
  await tester.pumpWidget(UncontrolledProviderScope(container: container, child: const AssistantApp()));
  await _settle(tester);
  return container.read(routerProvider);
}

/// 页面里有循环动画（加载闪光等），pumpAndSettle 等不到静止：走够过渡时长即可。
Future<void> _settle(WidgetTester tester) async {
  for (var i = 0; i < 12; i++) {
    await tester.pump(const Duration(milliseconds: 100));
  }
}

bool _barShown(WidgetTester tester) => tester.widget<FloatAway>(find.ancestor(of: find.byType(FloatingTopBar), matching: find.byType(FloatAway))).visible;

void main() {
  testWidgets('聊天历史抽屉打开时浮动顶栏让位，关上回来（v2.78 用户 15:30“还叠在一起”）', (tester) async {
    final router = await _pump(tester);
    router.go('/chat');
    await _settle(tester);
    expect(_barShown(tester), isTrue);
    await tester.tap(find.byTooltip('历史').first);
    await _settle(tester);
    expect(_barShown(tester), isFalse);
    await tester.flingFrom(const Offset(380, 400), const Offset(-300, 0), 1500); // v3.5.1 抽屉全屏、没有遮罩：左滑关
    await _settle(tester);
    expect(_barShown(tester), isTrue);
  });

  testWidgets('顶栏：一级页面和项目页显示（v2.93）、子页面隐藏；左侧按钮随 Tab 变', (tester) async {
    final router = await _pump(tester);
    expect(find.byType(FloatingTopBar), findsOneWidget);
    expect(_barShown(tester), isTrue);
    expect(find.byTooltip('新建面板'), findsOneWidget);

    await tester.tap(find.text('项目'));
    await _settle(tester);
    expect(find.byTooltip('新项目'), findsOneWidget);
    expect(_barShown(tester), isTrue);

    router.go('/projects/p1');
    await _settle(tester);
    expect(_barShown(tester), isTrue); // v2.93 §Q 项目页仍在一级外壳下
    expect(find.byTooltip('项目'), findsOneWidget); // 左上 ≡ = 项目切换（v2.95）

    router.go('/projects/p1/brief');
    await _settle(tester);
    expect(_barShown(tester), isFalse); // 规则与档案是子页面，自带标题栏

    await tester.tapAt(tester.getCenter(find.text('聊天'))); // 隐藏的顶栏不挡也不接点击
    await _settle(tester);
    expect(router.state.uri.path, '/projects/p1/brief');

    router.go('/chat');
    await _settle(tester);
    expect(_barShown(tester), isTrue);
    expect(find.byTooltip('历史'), findsOneWidget);
    expect(find.byTooltip('新对话'), findsNothing); // 新对话收进历史面板，顶部只留标题
    await tester.tap(find.byTooltip('历史'));
    await _settle(tester);
    expect(find.byTooltip('新对话'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('头像 → 我的（盖在外壳上），返回回到原来的 Tab', (tester) async {
    final router = await _pump(tester);
    await tester.tap(find.byTooltip('我的'));
    await _settle(tester);
    expect(router.state.uri.path, '/me');
    expect(find.text('个人资料'), findsOneWidget);
    expect(find.byTooltip('回到主页'), findsNothing); // 能返回：左上是返回钮（我的页没有 AppBar，是玻璃圆钮）
    await tester.tap(find.byTooltip('返回'));
    await _settle(tester);
    expect(router.state.uri.path, '/home');
  });

  testWidgets('深链直达 /me/usage：返回到“我的”，再返回去主页', (tester) async {
    final router = await _pump(tester);
    router.go('/me/usage');
    await _settle(tester);
    await tester.tap(find.byTooltip('返回')); // v3.5 子页返回是圆玻璃钮（不是 AppBar 的 BackButton，pageBack 找不到）
    await _settle(tester);
    expect(router.state.uri.path, '/me');
    await tester.tap(find.byTooltip('回到主页'));
    await _settle(tester);
    expect(router.state.uri.path, '/home');
    expect(_barShown(tester), isTrue);
  });

  testWidgets('v3.3 B4：外壳分支里打开子页（自带不透明壁纸）→ 外壳壁纸暂停、不重绘；返回一开始 / 切 Tab 就恢复，顶栏时机不变', (tester) async {
    final router = await _pump(tester);
    final shellSky = find.byWidgetPredicate((w) => w is SkyLayer && w.coverable);
    bool driving() => tester.state<SkyLayerState>(shellSky).driving;
    RenderObject paint() => tester.renderObject(find.descendant(of: shellSky, matching: find.byType(CustomPaint)));
    bool repaintsOnTick() {
      SkyClock.instance.time.value += 0.033; // 共享时钟走一格（子页那层仍在驱动它）
      return paint().debugNeedsPaint;
    }

    router.go('/projects/p1');
    await _settle(tester);
    expect(driving(), isTrue);
    await tester.pump();
    expect(repaintsOnTick(), isTrue, reason: '一级页面 / 项目页：外壳壁纸就是看到的那层');

    unawaited(router.push('/projects/p1/brief'));
    await _settle(tester);
    expect(_barShown(tester), isFalse);
    expect(driving(), isFalse, reason: '子页进场完成、完全盖住：外壳那层退订 SkyClock');
    await tester.pump();
    expect(repaintsOnTick(), isFalse, reason: '时钟仍在走（子页那层在驱动），但外壳那层不重画');

    router.go('/home'); // 切 Tab：项目分支（连同子页）进后台，主页要用外壳壁纸
    await _settle(tester);
    expect(driving(), isTrue);
    router.go('/projects/p1/brief');
    await _settle(tester);
    expect(driving(), isFalse);

    router.pop();
    await tester.pump(); // pop 的第一帧：已恢复，且这一帧就按此刻重画
    expect(driving(), isTrue, reason: '返回一开始就恢复，不等转场结束');
    await _settle(tester);
    expect(router.state.uri.path, '/projects/p1');
    expect(_barShown(tester), isTrue);
    expect(driving(), isTrue);
    await tester.pump();
    expect(repaintsOnTick(), isTrue);
    expect(tester.takeException(), isNull);
  });
}
