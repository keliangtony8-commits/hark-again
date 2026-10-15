// 设计 v2 外壳：浮动顶栏只在一级页面出现，进子页面淡出；头像进入“我的”（盖在外壳上，返回回到原处）；
// 深链直接落在 /me/… 时，“我的”的返回去主页而不是退出 App；一级页面的上下文按钮各就各位。
import 'package:assistant/app.dart';
import 'package:assistant/core/api.dart';
import 'package:assistant/core/chat_socket.dart';
import 'package:assistant/core/session.dart';
import 'package:assistant/shell/top_bar.dart';
import 'package:assistant/ui/motion.dart';
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
    await tester.tapAt(const Offset(390, 400)); // 点遮罩关抽屉
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
    expect(find.byTooltip('项目对话'), findsOneWidget); // 左上 ≡

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
    await tester.pageBack();
    await _settle(tester);
    expect(router.state.uri.path, '/me');
    await tester.tap(find.byTooltip('回到主页'));
    await _settle(tester);
    expect(router.state.uri.path, '/home');
    expect(_barShown(tester), isTrue);
  });
}
