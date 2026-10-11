// 搜索命中 → 打开对话并定位：message_id 解析；open(focus:) 一次性请求（takeFocus 只给一次、找不到就作废）；
// 界面：长对话里目标起初不在屏上，打开后被滚进视口并闪一下（FlashHighlight）；减少动态时同样到位。
import 'package:assistant/core/api.dart';
import 'package:assistant/core/cache.dart';
import 'package:assistant/core/chat_socket.dart';
import 'package:assistant/features/chat/chat_controller.dart';
import 'package:assistant/features/chat/chat_view.dart';
import 'package:assistant/models/resources.dart';
import 'package:assistant/theme/app_theme.dart';
import 'package:assistant/ui/motion.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'chat_controller_test.dart' show FakeSocket;

Map<String, dynamic> _msg(String id, String role, String text) => {
      'id': id,
      'role': role,
      'blocks': [
        {'type': 'text', 'text': text}
      ],
    };

class _Api implements Api {
  List<dynamic> messages = [];
  @override
  Future<dynamic> get(String path) async {
    if (path.startsWith('/api/conversations/')) return {'id': path.split('/').last, 'messages': messages};
    if (path.startsWith('/api/conversations')) return <dynamic>[];
    return null;
  }

  @override
  dynamic noSuchMethod(Invocation i) => throw UnimplementedError();
}

/// 60 条消息，m5 在很上面（打开时在屏外）。
List<dynamic> _long() => [for (var i = 0; i < 60; i++) _msg('m$i', i.isEven ? 'user' : 'assistant', '第 $i 条消息\n' * 3)];

ProviderContainer _container(_Api api) {
  final c = ProviderContainer(overrides: [
    chatSocketProvider.overrideWithValue(FakeSocket()),
    apiProvider.overrideWithValue(api),
    cacheStoreProvider.overrideWithValue(MemoryCacheStore()),
  ]);
  addTearDown(c.dispose);
  return c;
}

void main() {
  test('搜索结果带 message_id', () {
    final s = ConversationSummary.fromJson({'id': 'c', 'title': 't', 'snippet': '…x…', 'message_id': 'm9'});
    expect(s.messageId, 'm9');
    expect(ConversationSummary.fromJson({'id': 'c', 'title': 't'}).messageId, isNull);
  });

  test('open(focus:)：一次性；找不到就作废；打开新对话清掉', () async {
    final api = _Api()..messages = _long();
    final c = _container(api);
    final ctl = c.read(chatProvider('').notifier);

    await ctl.open('c1', focus: 'm5');
    expect(c.read(chatProvider('')).focus, 'm5');
    expect(ctl.takeFocus(), 'm5');
    expect(ctl.takeFocus(), isNull); // 只给一次

    await ctl.open('c1', focus: 'gone'); // 已被删掉的消息
    expect(c.read(chatProvider('')).focus, isNull);

    await ctl.open('c1', focus: 'm5');
    await ctl.open(null, focus: 'm5');
    expect(c.read(chatProvider('')).focus, isNull);
  });

  for (final reduce in [false, true]) {
    testWidgets('界面：目标滚进视口并闪一下（减少动态=$reduce）', (tester) async {
      final api = _Api()..messages = _long();
      final c = _container(api);
      await tester.pumpWidget(UncontrolledProviderScope(
        container: c,
        child: MediaQuery(
          data: MediaQueryData(size: const Size(400, 800), disableAnimations: reduce),
          child: MaterialApp(theme: buildTheme(Brightness.light), home: const Scaffold(body: ChatView())),
        ),
      ));
      await c.read(chatProvider('').notifier).open('c1');
      await tester.pumpAndSettle();
      expect(find.textContaining('第 5 条消息'), findsNothing); // 起初在屏外（懒加载没建）

      await c.read(chatProvider('').notifier).open('c1', focus: 'm5');
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 50));
      await tester.pumpAndSettle();

      final target = find.textContaining('第 5 条消息');
      expect(target, findsOneWidget);
      final box = tester.getRect(target);
      expect(box.top, greaterThanOrEqualTo(0));
      expect(box.bottom, lessThanOrEqualTo(800));
      expect(c.read(chatProvider('')).focus, isNull); // 已取走

      final flash = tester.widget<FlashHighlight>(find.ancestor(of: target, matching: find.byType(FlashHighlight)));
      expect(flash.play, greaterThan(0));
      await tester.pump(const Duration(seconds: 2)); // 闪完（含减少动态的停留计时）
    });
  }

  // 回归（v0.90）：上一个对话往回翻的位置被带进新对话，新对话最后一张卡压在输入胶囊下。
  testWidgets('换对话回到最新一条', (tester) async {
    final api = _Api()..messages = _long();
    final c = _container(api);
    await tester.pumpWidget(UncontrolledProviderScope(
      container: c,
      child: MediaQuery(
        data: const MediaQueryData(size: Size(400, 800)),
        child: MaterialApp(theme: buildTheme(Brightness.light), home: const Scaffold(body: ChatView())),
      ),
    ));
    await c.read(chatProvider('').notifier).open('c1');
    await tester.pumpAndSettle();
    await tester.drag(find.byType(ListView), const Offset(0, 1500)); // 往回翻
    await tester.pumpAndSettle();
    expect(find.textContaining('第 59 条消息'), findsNothing);

    await c.read(chatProvider('').notifier).open('c2');
    await tester.pumpAndSettle();
    expect(find.textContaining('第 59 条消息'), findsOneWidget);
    expect(tester.widget<ListView>(find.byType(ListView)).controller!.offset, 0);
  });

  // 回归（v0.25–v0.42）：FlashHighlight 的 Stack 放松了宽度约束，用户气泡缩到左边。
  testWidgets('布局：用户气泡贴右、回复贴左', (tester) async {
    tester.view.devicePixelRatio = 1;
    tester.view.physicalSize = const Size(400, 800);
    addTearDown(tester.view.reset);
    final api = _Api()..messages = [_msg('u1', 'user', '短问题'), _msg('a1', 'assistant', '回答')];
    final c = _container(api);
    await tester.pumpWidget(UncontrolledProviderScope(
      container: c,
      child: MaterialApp(theme: buildTheme(Brightness.light), home: const Scaffold(body: ChatView())),
    ));
    await c.read(chatProvider('').notifier).open('c1');
    await tester.pumpAndSettle();

    final user = tester.getRect(find.text('短问题'));
    final reply = tester.getRect(find.textContaining('回答'));
    expect(user.right, greaterThan(400 - 60)); // 右缘贴近屏幕右边（减去列表内边距与气泡内边距）
    expect(user.left, greaterThan(200));
    expect(reply.left, lessThan(60));
  });
}
