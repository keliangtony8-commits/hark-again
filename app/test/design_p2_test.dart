// 设计 v2 P2：日期分隔（startsNewDay / formatDay）、气泡左右与最大宽度、聊天列表让出浮动输入胶囊、
// 一级页面的输入胶囊（聚焦磨砂 + 收起钮 + 建议问题，发出 = 新对话并切到聊天）。
import 'package:assistant/app.dart';
import 'package:assistant/core/api.dart';
import 'package:assistant/core/cache.dart';
import 'package:assistant/core/chat_socket.dart';
import 'package:assistant/core/session.dart';
import 'package:assistant/features/chat/chat_controller.dart';
import 'package:assistant/features/chat/chat_view.dart';
import 'package:assistant/features/chat/composer.dart';
import 'package:assistant/features/chat/message_view.dart';
import 'package:assistant/models/message.dart';
import 'package:assistant/theme/app_theme.dart';
import 'package:assistant/theme/tokens.dart';
import 'package:assistant/ui/format.dart';
import 'package:assistant/ui/glass.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'chat_controller_test.dart' show FakeSocket;

Map<String, dynamic> _msg(String id, String role, String text, [String? at]) => {
      'id': id,
      'role': role,
      'blocks': [
        {'type': 'text', 'text': text}
      ],
      'created_at': ?at,
    };

Message _m(String id, DateTime? at) => Message(id: id, role: 'user', blocks: const [], createdAt: at);

class _ChatApi implements Api {
  _ChatApi(this.messages);
  final List<dynamic> messages;
  @override
  Future<dynamic> get(String path) async {
    if (path.startsWith('/api/conversations/')) return {'id': 'c1', 'messages': messages};
    if (path.startsWith('/api/conversations')) return <dynamic>[];
    return null;
  }

  @override
  dynamic noSuchMethod(Invocation i) => throw UnimplementedError();
}

class _SignedIn extends SessionNotifier {
  @override
  Future<Session> build() async => const Session(server: 'http://x', token: 't');
}

class _ShellApi implements Api {
  @override
  Future<dynamic> get(String path) async => path == '/api/inbox' ? {'unread': 0, 'latest': null} : <dynamic>[];
  @override
  dynamic noSuchMethod(Invocation i) => throw UnimplementedError();
}

Future<void> _frames(WidgetTester tester, [int n = 12]) async {
  for (var i = 0; i < n; i++) {
    await tester.pump(const Duration(milliseconds: 100));
  }
}

void main() {
  group('日期分隔', () {
    final now = DateTime(2026, 10, 11, 10);
    test('formatDay：今天 / 昨天 / 今年 / 往年', () {
      expect(formatDay(DateTime(2026, 10, 11, 0, 1), now: now), '今天');
      expect(formatDay(DateTime(2026, 10, 10, 23, 59), now: now), '昨天');
      expect(formatDay(DateTime(2026, 10, 9), now: now), '10月9日 星期五');
      expect(formatDay(DateTime(2025, 10, 9), now: now), '2025年10月9日 星期四');
      expect(formatDate(now), '10月11日 星期日');
    });

    test('startsNewDay：第一条有时间的消息、跨本地日才分；没时间的消息不开新的一天', () {
      final ms = [
        _m('a', null), // 老服务器 / 占位：不画
        _m('b', DateTime(2026, 10, 10, 23)),
        _m('c', DateTime(2026, 10, 10, 23, 30)),
        _m('d', null),
        _m('e', DateTime(2026, 10, 11, 0, 5)), // 越过 d 跟 c 比：跨天
      ];
      expect([for (var i = 0; i < ms.length; i++) startsNewDay(ms, i)], [false, true, false, false, true]);
    });

    test('created_at 解析成本地时间；不带时就是 null', () {
      final m = Message.fromJson(_msg('x', 'user', 'hi', '2026-10-10T16:30:00+00:00'));
      expect(m.createdAt, DateTime.utc(2026, 10, 10, 16, 30).toLocal());
      expect(Message.fromJson(_msg('y', 'user', 'hi')).createdAt, isNull);
    });
  });

  testWidgets('聊天：跨天插日期，用户靠右、回复是左侧玻璃卡，最后一条不被输入胶囊挡住', (tester) async {
    tester.view.physicalSize = const Size(400, 800);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    final now = DateTime.now();
    final yesterday = now.subtract(const Duration(days: 1)).toUtc().toIso8601String();
    final today = now.toUtc().toIso8601String();
    final c = ProviderContainer(overrides: [
      chatSocketProvider.overrideWithValue(FakeSocket()),
      apiProvider.overrideWithValue(_ChatApi([
        _msg('u1', 'user', '昨天的问题', yesterday),
        _msg('a1', 'assistant', '昨天的回答', yesterday),
        _msg('u2', 'user', '今天的问题', today),
        _msg('a2', 'assistant', '今天的回答', today),
      ])),
      cacheStoreProvider.overrideWithValue(MemoryCacheStore()),
    ]);
    addTearDown(c.dispose);
    await tester.pumpWidget(UncontrolledProviderScope(
      container: c,
      child: MaterialApp(theme: buildTheme(Brightness.light), home: const Scaffold(body: ChatView())),
    ));
    await c.read(chatProvider('').notifier).open('c1');
    await tester.pumpAndSettle();

    expect(find.byType(DaySeparator), findsNWidgets(2));
    expect(find.text('昨天'), findsOneWidget);
    expect(find.text('今天'), findsOneWidget);
    // 日期在当天第一条消息上方
    expect(tester.getTopLeft(find.text('今天')).dy, lessThan(tester.getTopLeft(find.text('今天的问题')).dy));

    final user = tester.getRect(find.text('今天的问题'));
    final reply = tester.getRect(find.ancestor(of: find.text('今天的回答'), matching: find.byType(GlassSurface)).first);
    expect(user.right, greaterThan(400 - Sp.x4 - Sp.x5)); // 靠右
    expect(reply.left, lessThan(Sp.x4 + 1)); // 靠左
    expect(reply.width, lessThanOrEqualTo((400 - Sp.x4 * 2) * Layout.bubbleMax + 0.5)); // 不铺满：留出一侧

    // 列表让出浮动输入胶囊：最后一条回复（和它的操作行）都在胶囊上方
    final composerTop = tester.getTopLeft(find.byType(Composer)).dy;
    expect(tester.getBottomLeft(find.byTooltip('重新生成')).dy, lessThanOrEqualTo(composerTop + Sp.x3));
  });

  testWidgets('一级页面输入胶囊：聚焦 → 磨砂 + 收起钮 + 建议；点建议 = 新对话发出并切到聊天', (tester) async {
    tester.view.physicalSize = const Size(400, 860);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    SharedPreferences.setMockInitialValues({});
    final socket = FakeSocket();
    final container = ProviderContainer(overrides: [
      sessionProvider.overrideWith(_SignedIn.new),
      apiProvider.overrideWithValue(_ShellApi()),
      chatSocketProvider.overrideWithValue(socket),
      cacheStoreProvider.overrideWithValue(MemoryCacheStore()),
    ]);
    addTearDown(container.dispose);
    await tester.pumpWidget(UncontrolledProviderScope(container: container, child: const AssistantApp()));
    await _frames(tester);

    expect(find.byType(Composer), findsOneWidget); // 主页底部就有
    expect(find.text('给助手发消息'), findsOneWidget);
    expect(find.byTooltip('收起'), findsNothing);
    expect(tester.widget<FrostScrim>(find.byType(FrostScrim)).visible, isFalse);

    await tester.tap(find.byType(TextField));
    await _frames(tester, 5);
    expect(find.byTooltip('收起'), findsOneWidget);
    expect(tester.widget<FrostScrim>(find.byType(FrostScrim)).visible, isTrue);
    expect(find.text('查一下今天的新闻'), findsOneWidget);

    await tester.tap(find.byTooltip('收起'));
    await _frames(tester, 5);
    expect(find.byTooltip('收起'), findsNothing);
    expect(tester.widget<FrostScrim>(find.byType(FrostScrim)).visible, isFalse);

    await tester.tap(find.byType(TextField));
    await _frames(tester, 5);
    await tester.tap(find.text('查一下今天的新闻'));
    await _frames(tester);
    expect(container.read(routerProvider).state.uri.path, '/chat');
    expect(socket.sent.last['type'], 'user.message');
    expect(socket.sent.last['text'], '查一下今天的新闻');
    expect(GoRouter.of(tester.element(find.byType(ChatView))).state.uri.path, '/chat');
  });
}
