// 本对话用量：解析 + 标题下一行的措辞（有钱 / 只有 token / 没调用过 → 不显示）；
// 聊天页打开对话后标题下出现用量，一轮回复结束自动刷新，新对话不显示也不可点；点标题弹出按模型明细。
import 'package:assistant/core/api.dart';
import 'package:assistant/core/cache.dart';
import 'package:assistant/core/chat_socket.dart';
import 'package:assistant/features/chat/chat_controller.dart';
import 'package:assistant/features/chat/chat_screen.dart';
import 'package:assistant/features/chat/conversation_usage.dart';
import 'package:assistant/models/usage.dart';
import 'package:assistant/theme/app_theme.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'chat_controller_test.dart' show FakeSocket;

Map<String, dynamic> usage({double cost = 0.012, int calls = 2, List<String> priced = const ['fast', 'smart']}) => {
      'currency': 'CNY',
      'priced': priced,
      'total': {
        'calls': calls,
        'tokens': calls == 0 ? 0 : 3400,
        'cost': cost,
        'models': [
          if (calls > 0) {'model': 'smart', 'calls': 1, 'prompt_tokens': 1500, 'completion_tokens': 500, 'cost': cost},
          if (calls > 1) {'model': 'fast', 'calls': calls - 1, 'prompt_tokens': 1200, 'completion_tokens': 200, 'cached_tokens': 1080, 'cost': 0},
        ],
      },
    };

class _Api implements Api {
  Map<String, dynamic> body = usage();
  int usageCalls = 0;

  @override
  Future<dynamic> get(String path) async {
    if (path.endsWith('/usage')) {
      usageCalls++;
      return body;
    }
    if (path.startsWith('/api/conversations/')) {
      return {
        'id': 'c1',
        'messages': [
          {'id': 'u1', 'role': 'user', 'blocks': [{'type': 'text', 'text': '嗨'}]},
          {'id': 'a1', 'role': 'assistant', 'blocks': [{'type': 'text', 'text': '你好'}]},
        ],
      };
    }
    if (path.startsWith('/api/conversations')) {
      return [
        {'id': 'c1', 'title': '旧对话', 'updated_at': '2026-10-11T00:00:00Z'},
      ];
    }
    if (path == '/api/catalog/models') return {'default': 'fast', 'models': []};
    return null;
  }

  @override
  dynamic noSuchMethod(Invocation i) => throw UnimplementedError();
}

void main() {
  test('标题下一行：有单价显示钱 + token，没单价只显示 token，没调用过不显示', () {
    expect(usageLine(UsageTotal.fromJson(usage())), '¥0.012 · 3.4K token');
    expect(usageLine(UsageTotal.fromJson(usage(priced: const []))), '3.4K token');
    expect(usageLine(UsageTotal.fromJson(usage(calls: 0))), isNull);
    expect(UsageTotal.fromJson(usage(priced: const ['smart'])).hasUnpriced, isTrue);
    expect(UsageTotal.fromJson(usage()).hasUnpriced, isFalse);
  });

  testWidgets('打开对话 → 标题下出现用量；回复结束刷新；点开看明细；新对话不显示', (tester) async {
    final socket = FakeSocket();
    final api = _Api();
    await tester.pumpWidget(ProviderScope(
      overrides: [
        chatSocketProvider.overrideWithValue(socket),
        apiProvider.overrideWithValue(api),
        cacheStoreProvider.overrideWithValue(MemoryCacheStore()),
      ],
      child: MaterialApp(theme: buildTheme(Brightness.light), home: const ChatScreen()),
    ));
    await tester.pumpAndSettle();
    expect(find.bySemanticsLabel('本对话用量'), findsNothing); // 新对话：没有用量，也不可点
    expect(api.usageCalls, 0);

    final container = ProviderScope.containerOf(tester.element(find.byType(ChatScreen)));
    await container.read(chatProvider('').notifier).open('c1');
    await tester.pumpAndSettle();
    expect(find.text('¥0.012 · 3.4K token'), findsOneWidget);
    expect(api.usageCalls, 1);

    // 发一条 → 回复结束 → 自动重新取一次，文字换成新值
    api.body = usage(cost: 0.02, calls: 3);
    container.read(chatProvider('').notifier).send('再问');
    socket.ctl.add({'type': 'message.start', 'conversation_id': 'c1', 'user_message_id': 'u2', 'title': '旧对话'});
    await tester.pump();
    socket.ctl.add({
      'type': 'message.done',
      'message': {'id': 'a2', 'role': 'assistant', 'blocks': [{'type': 'text', 'text': '好'}]},
    });
    await tester.pumpAndSettle();
    expect(api.usageCalls, 2);
    expect(find.text('¥0.020 · 3.4K token'), findsOneWidget);

    await tester.tap(find.text('¥0.020 · 3.4K token'));
    await tester.pumpAndSettle();
    expect(find.text('本对话用量'), findsOneWidget);
    expect(find.text('3 次调用 · 输入 2.7K · 输出 700 · 缓存命中 40%'), findsOneWidget); // 1080 / 2700
    expect(find.textContaining('缓存命中 90%'), findsOneWidget); // fast 那一行
    expect(find.text('smart'), findsOneWidget);
    expect(find.text('fast'), findsOneWidget);

    Navigator.of(tester.element(find.text('本对话用量'))).pop();
    await tester.pumpAndSettle();
    await container.read(chatProvider('').notifier).open(null);
    await tester.pumpAndSettle();
    expect(find.textContaining('token'), findsNothing);
  });
}
