// 设计 v2 外壳：浮动顶栏只在一级页面出现，进子页面淡出；一级页面的上下文按钮各就各位。
// v3.5.1：“我的”= 第四个分支——点头像顶栏仍在、三个分段都不选中、头像高亮、无返回钮；进出“我的”整页横滑；返回键在“我的”回主页；
// 深链直接落在 /me/… 时返回回到“我的”。
import 'dart:async';

import 'package:assistant/app.dart';
import 'package:assistant/core/api.dart';
import 'package:assistant/core/chat_socket.dart';
import 'package:assistant/core/session.dart';
import 'package:assistant/features/home/home_screen.dart';
import 'package:assistant/features/me/me_screen.dart';
import 'package:assistant/features/projects/projects_screen.dart';
import 'package:assistant/shell/app_shell.dart';
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

  testWidgets('v3.5.1 点头像 → 我的：顶栏仍在、三个分段都不选中、头像高亮、无返回钮；横滑切过去；点主页切回', (tester) async {
    final router = await _pump(tester);
    double dx(Type page) => tester.widget<FractionalTranslation>(find.ancestor(of: find.byType(page), matching: find.byType(FractionalTranslation)).first).translation.dx;
    double opacity(String key) => tester.widget<AnimatedOpacity>(find.byKey(Key(key))).opacity;

    await tester.tap(find.byTooltip('我的'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 120)); // 滑到一半：主页向左滑出、“我的”从右滑入，两页都在台上
    expect(dx(HomeScreen), lessThan(0));
    expect(dx(MeScreen), greaterThan(0));
    await _settle(tester);

    expect(router.state.uri.path, '/me');
    expect(find.text('个人资料'), findsOneWidget);
    expect(_barShown(tester), isTrue, reason: '“我的”是一级分支，顶栏不消失');
    expect(tester.widget<FloatingTopBar>(find.byType(FloatingTopBar)).index, meBranch);
    expect(opacity('nav-thumb'), 0, reason: '三个分段都不选中：滑块淡出');
    expect(opacity('avatar-ring'), 1, reason: '头像高亮为当前项');
    expect(find.byTooltip('返回'), findsNothing);
    expect(find.byTooltip('回到主页'), findsNothing);
    expect(dx(MeScreen), 0);
    expect(find.byType(HomeScreen, skipOffstage: true), findsNothing, reason: '滑完离场页下台');

    await tester.tap(find.text('主页'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 120)); // 反向：“我的”向右滑出、主页从左滑入
    expect(dx(MeScreen), greaterThan(0));
    expect(dx(HomeScreen), lessThan(0));
    await _settle(tester);
    expect(router.state.uri.path, '/home');
    expect(opacity('nav-thumb'), 1);
    expect(opacity('avatar-ring'), 0);
    expect(dx(HomeScreen), 0);
    expect(tester.takeException(), isNull);
  });

  testWidgets('主页 / 聊天 / 项目之间照旧直接切换（不横滑）', (tester) async {
    await _pump(tester);
    await tester.tap(find.text('项目'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 120));
    expect(find.byType(HomeScreen, skipOffstage: true), findsNothing);
    final t = tester.widget<FractionalTranslation>(find.ancestor(of: find.byType(ProjectsScreen), matching: find.byType(FractionalTranslation)).first);
    expect(t.translation, Offset.zero);
  });

  testWidgets('返回键在“我的”回主页（主页状态原样）；在主页上的“我的”子页（push）返回回主页', (tester) async {
    final router = await _pump(tester);
    router.go('/me');
    await _settle(tester);
    await tester.binding.handlePopRoute();
    await _settle(tester);
    expect(router.state.uri.path, '/home');
    expect(_barShown(tester), isTrue);

    unawaited(router.push('/me/usage')); // 主页卡片 / 聊天块打开“我的”子页：叠在当前页上
    await _settle(tester);
    expect(_barShown(tester), isFalse);
    router.pop();
    await _settle(tester);
    expect(router.state.uri.path, '/home');
    expect(_barShown(tester), isTrue);
  });

  testWidgets('深链直达 /me/usage：返回到“我的”，再返回去主页', (tester) async {
    final router = await _pump(tester);
    router.go('/me/usage');
    await _settle(tester);
    expect(_barShown(tester), isFalse); // 子页：顶栏让位，自带返回钮
    await tester.tap(find.byTooltip('返回')); // v3.5 子页返回是圆玻璃钮（不是 AppBar 的 BackButton，pageBack 找不到）
    await _settle(tester);
    expect(router.state.uri.path, '/me');
    expect(_barShown(tester), isTrue);
    await tester.binding.handlePopRoute();
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

  testWidgets('减少动态：进出“我的”直接切换，不横滑', (tester) async {
    Widget at(int i) => MediaQuery(
          data: const MediaQueryData(disableAnimations: true),
          child: Directionality(textDirection: TextDirection.ltr, child: ShellBranches(index: i, children: const [Text('a'), Text('b'), Text('c'), Text('d')])),
        );
    await tester.pumpWidget(at(0));
    await tester.pumpWidget(at(meBranch));
    await tester.pump(const Duration(milliseconds: 50));
    expect(find.text('a'), findsNothing, reason: '离场页立刻下台');
    final t = tester.widget<FractionalTranslation>(find.ancestor(of: find.text('d'), matching: find.byType(FractionalTranslation)));
    expect(t.translation, Offset.zero);
  });
}
