// §J：长按 = 原地聚焦菜单（ui/focus_menu.dart）+ “回复”= 引用回复（§C reply_to 的用户侧）。
// 菜单在被按的那条旁边（同侧）、点空白收起；回复 → 输入框顶上引用条 → 发出带 reply_to → 气泡顶上引用行；
// 服务器给的 quote 照画、原消息已删 = “原消息已删除”；✕ 取消引用；没落库的消息不给“回复”。
import 'package:assistant/core/api.dart';
import 'package:assistant/core/cache.dart';
import 'package:assistant/core/chat_socket.dart';
import 'package:assistant/features/chat/chat_controller.dart';
import 'package:assistant/features/chat/chat_view.dart';
import 'package:assistant/features/chat/quote_line.dart';
import 'package:assistant/models/block.dart';
import 'package:assistant/models/message.dart';
import 'package:assistant/theme/app_theme.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'chat_controller_test.dart' show FakeSocket;

Map<String, dynamic> _msg(String id, String role, String text, {Map<String, dynamic>? quote}) => {
      'id': id,
      'role': role,
      'created_at': DateTime.now().toUtc().toIso8601String(),
      'blocks': [
        {'type': 'text', 'text': text}
      ],
      if (quote != null) ...{'reply_to': quote['id'], 'quote': quote},
    };

class _Api implements Api {
  _Api(this.messages);
  List<dynamic> messages;
  @override
  Future<dynamic> get(String path) async {
    if (path.startsWith('/api/conversations/')) return {'id': 'c1', 'messages': messages};
    if (path.startsWith('/api/conversations')) return <dynamic>[];
    return null;
  }

  @override
  dynamic noSuchMethod(Invocation i) => throw UnimplementedError();
}

Future<FakeSocket> _chat(WidgetTester tester, List<dynamic> messages) async {
  tester.view.physicalSize = const Size(412, 915);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  final socket = FakeSocket();
  final container = ProviderContainer(overrides: [
    chatSocketProvider.overrideWithValue(socket),
    apiProvider.overrideWithValue(_Api(messages)),
    cacheStoreProvider.overrideWithValue(MemoryCacheStore()),
  ]);
  addTearDown(container.dispose);
  await tester.pumpWidget(UncontrolledProviderScope(
    container: container,
    child: MaterialApp(theme: buildTheme(Brightness.dark), home: const Scaffold(body: ChatView())),
  ));
  await container.read(chatProvider('').notifier).open('c1');
  await tester.pumpAndSettle();
  return socket;
}

void main() {
  testWidgets('长按回复：菜单紧贴在它下方、左对齐；点空白收起', (tester) async {
    await _chat(tester, [_msg('u1', 'user', '明天几点出发'), _msg('a1', 'assistant', '八点半出发最稳')]);
    final reply = tester.getRect(find.text('八点半出发最稳'));
    await tester.longPress(find.text('八点半出发最稳'));
    await tester.pumpAndSettle();
    final copy = tester.getRect(find.text('复制'));
    expect(copy.left, lessThan(reply.left + 60)); // 同侧（左）
    expect((copy.top - reply.bottom).abs() < 120 || copy.bottom < reply.top, isTrue); // 紧贴上 / 下
    await tester.tapAt(const Offset(390, 120));
    await tester.pumpAndSettle();
    expect(find.text('复制'), findsNothing);
  });

  testWidgets('回复 → 引用条 → 发出带 reply_to → 气泡顶上引用行；✕ 取消', (tester) async {
    final socket = await _chat(tester, [_msg('u1', 'user', '明天几点出发'), _msg('a1', 'assistant', '八点半出发最稳')]);
    await tester.longPress(find.text('八点半出发最稳'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('回复'));
    await tester.pumpAndSettle();
    expect(find.byType(QuoteBar), findsOneWidget);
    // ✕ 取消
    await tester.tap(find.byTooltip('不回复这条'));
    await tester.pumpAndSettle();
    expect(find.byType(QuoteBar), findsNothing);

    await tester.longPress(find.text('八点半出发最稳'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('回复'));
    await tester.pumpAndSettle();
    await tester.enterText(find.byType(TextField), '那七点呢');
    await tester.testTextInput.receiveAction(TextInputAction.send);
    await tester.pumpAndSettle();
    if (socket.sent.isEmpty) {
      await tester.tap(find.bySemanticsLabel('发送'));
      await tester.pumpAndSettle();
    }
    final sent = socket.sent.lastWhere((e) => e['type'] == 'user.message');
    expect(sent['reply_to'], 'a1');
    expect(sent['text'], '那七点呢');
    expect(find.byType(QuoteBar), findsNothing); // 发出就清掉
    expect(find.byType(QuoteLine), findsOneWidget); // 本机气泡已带引用行
  });

  testWidgets('服务器给的 quote：照画；原消息已删 = 原消息已删除', (tester) async {
    await _chat(tester, [
      _msg('a1', 'assistant', '第一步先备份'),
      _msg('u1', 'user', '具体怎么做', quote: {'id': 'a1', 'role': 'assistant', 'text': '第一步先备份'}),
      _msg('u2', 'user', '那个呢', quote: {'id': 'gone', 'missing': true}),
    ]);
    expect(find.byType(QuoteLine), findsNWidgets(2));
    expect(find.text(MessageQuote.missingText), findsOneWidget);
    expect(find.text('第一步先备份'), findsNWidgets(2)); // 原消息 + 引用行
  });

  test('MessageQuote：取一行、截断、附件名、missing', () {
    final long = '字' * 300;
    final q = MessageQuote.of(Message(id: 'x', role: 'assistant', blocks: [TextBlock('a\n  b'), TextBlock(long)]));
    expect(q.text.length, MessageQuote.snippet);
    expect(q.text.startsWith('a b'), isTrue);
    final f = MessageQuote.of(const Message(id: 'y', role: 'user', blocks: [FileBlock(source: 'upload', id: 'f', name: '报表.xlsx', mime: 'x', size: 1)]));
    expect(f.text, '[附件] 报表.xlsx');
    expect(MessageQuote.fromJson({'id': 'z', 'missing': true})!.line, MessageQuote.missingText);
    expect(MessageQuote.fromJson(null), isNull);
  });
}
