// 模型调用重试提示（v1.50，WS turn.retry）：文字规则、控制器挂到占位消息上 / 新内容一到就收起 / 备用模型提示留到这一轮结束，
// 回复上方那一行的渲染。
import 'package:assistant/core/api.dart';
import 'package:assistant/core/cache.dart';
import 'package:assistant/core/chat_socket.dart';
import 'package:assistant/features/chat/chat_controller.dart';
import 'package:assistant/features/chat/message_view.dart';
import 'package:assistant/features/chat/retry_line.dart';
import 'package:assistant/models/message.dart';
import 'package:assistant/models/retry_notice.dart';
import 'package:assistant/theme/app_theme.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'chat_controller_test.dart' show FakeSocket;

class _Api implements Api {
  @override
  Future<dynamic> get(String path) async {
    if (path.startsWith('/api/conversations/')) return {'id': 'c1', 'messages': <dynamic>[]};
    if (path.startsWith('/api/conversations')) return <dynamic>[];
    return null;
  }

  @override
  dynamic noSuchMethod(Invocation i) => throw UnimplementedError();
}

Future<void> _settle() async {
  for (var i = 0; i < 5; i++) {
    await Future<void>.delayed(Duration.zero);
  }
}

// 等待卡里的跳点是无限动画：不能 pumpAndSettle
Future<void> _pump(WidgetTester t) async {
  await t.pump();
  await t.pump(const Duration(milliseconds: 600));
}

Widget _host(Message m) => ProviderScope(
      child: MaterialApp(
        theme: buildTheme(Brightness.light),
        home: Scaffold(body: SizedBox(width: 400, child: MessageView(m))),
      ),
    );

void main() {
  test('文字规则', () {
    const r = RetryNotice(attempt: 2, max: 5, delayMs: 1000, reason: '模型那边限流了');
    expect(retryNoticeText(r), '模型那边限流了，正在重试 2/5');
    expect(retryNoticeSemantics(r), contains('不用操作'));
    expect(retryNoticeText(const RetryNotice(attempt: 0, max: 0, delayMs: 0, reason: '网络断了')), '网络断了，正在重试');
    const f = RetryNotice(attempt: 0, max: 5, delayMs: 0, reason: '模型服务器出错了', fallback: 'fast', fallbackLabel: '快速');
    expect(f.isFallback, true);
    expect(retryNoticeText(f), '刚才模型服务器出错了，这一轮改用「快速」');
    expect(retryNoticeText(const RetryNotice(attempt: 0, max: 5, delayMs: 0, reason: 'x', fallback: 'fast')), contains('「fast」'));
    final bad = RetryNotice.fromJson({'attempt': 'x', 'reason': '  ', 'fallback': ''});
    expect((bad.attempt, bad.max, bad.reason, bad.isFallback), (0, 0, '模型调用失败', false));
    final ok = RetryNotice.fromJson({'attempt': 1, 'max': 3, 'delay_ms': 500, 'reason': '模型太久没回应', 'code': 'TIMEOUT'});
    expect((ok.attempt, ok.max, ok.delayMs, ok.code), (1, 3, 500, 'TIMEOUT'));
  });

  test('copyWith 能清掉 retry', () {
    const m = Message(id: 'p', role: 'assistant', blocks: [], pending: true, retry: RetryNotice(attempt: 1, max: 3, delayMs: 1, reason: 'x'));
    expect(m.copyWith(pending: true).retry, isNotNull);
    expect(m.copyWith(retry: () => null).retry, isNull);
  });

  test('控制器：挂上 → 新内容收起；备用模型提示留着，后续重试不盖掉模型名；完成后没有', () async {
    final socket = FakeSocket();
    final c = ProviderContainer(overrides: [
      chatSocketProvider.overrideWithValue(socket),
      apiProvider.overrideWithValue(_Api()),
      cacheStoreProvider.overrideWithValue(MemoryCacheStore()),
    ]);
    addTearDown(c.dispose);
    c.listen(chatProvider(''), (_, _) {});
    final ctl = c.read(chatProvider('').notifier);
    await ctl.open('c1');
    ctl.send('你好');
    socket.ctl.add({'type': 'message.start', 'conversation_id': 'c1', 'user_message_id': 'u1', 'title': 't'});
    socket.ctl.add({'type': 'block.start', 'index': 0, 'block': {'type': 'text', 'text': ''}});
    socket.ctl.add({'type': 'block.delta', 'index': 0, 'text': '半截'});
    // 服务器撤回半截（block.update 清空）后发 turn.retry：block.update 不能把刚挂上的提示收掉
    socket.ctl.add({'type': 'block.update', 'index': 0, 'block': {'type': 'text', 'text': ''}});
    socket.ctl.add({'type': 'turn.retry', 'attempt': 1, 'max': 3, 'delay_ms': 500, 'reason': '连接模型的网络断了', 'code': 'TRANSPORT'});
    await _settle();
    var last = c.read(chatProvider('')).messages.last;
    expect(last.retry?.attempt, 1);
    socket.ctl.add({'type': 'block.update', 'index': 0, 'block': {'type': 'text', 'text': ''}});
    await _settle();
    expect(c.read(chatProvider('')).messages.last.retry, isNotNull);
    socket.ctl.add({'type': 'block.delta', 'index': 0, 'text': '重来'});
    await _settle();
    last = c.read(chatProvider('')).messages.last;
    expect(last.retry, isNull);
    expect(last.blocks.length, 1);

    socket.ctl.add({'type': 'turn.retry', 'attempt': 0, 'max': 3, 'delay_ms': 0, 'reason': '模型服务器出错了', 'code': 'SERVER', 'fallback': 'fast', 'fallback_label': '快速'});
    await _settle();
    socket.ctl.add({'type': 'block.delta', 'index': 0, 'text': '继续'});
    socket.ctl.add({'type': 'tool.status', 'id': 't1', 'name': 'x', 'label': '正在试', 'state': 'running'});
    await _settle();
    expect(c.read(chatProvider('')).messages.last.retry?.fallbackLabel, '快速');
    socket.ctl.add({'type': 'turn.retry', 'attempt': 1, 'max': 3, 'delay_ms': 500, 'reason': '模型那边限流了', 'code': 'RATE_LIMIT'});
    await _settle();
    last = c.read(chatProvider('')).messages.last;
    expect((last.retry?.attempt, last.retry?.fallbackLabel), (1, '快速'));

    socket.ctl.add({
      'type': 'message.done',
      'message': {'id': 'a1', 'role': 'assistant', 'blocks': [{'type': 'text', 'text': '重来继续'}]}
    });
    await _settle();
    last = c.read(chatProvider('')).messages.last;
    expect((last.pending, last.retry), (false, null));
  });

  testWidgets('回复上方那一行：生成中显示、次数变化换字、完成后收起', (tester) async {
    const pending = Message(id: 'pending', role: 'assistant', blocks: [], pending: true,
        retry: RetryNotice(attempt: 1, max: 3, delayMs: 500, reason: '模型那边限流了'));
    await tester.pumpWidget(_host(pending));
    await _pump(tester);
    expect(find.byType(RetryLine), findsOneWidget);
    expect(find.text('模型那边限流了，正在重试 1/3'), findsOneWidget);
    expect(find.bySemanticsLabel(RegExp('不用操作')), findsOneWidget);

    await tester.pumpWidget(_host(pending.copyWith(retry: () => const RetryNotice(attempt: 2, max: 3, delayMs: 500, reason: '模型那边限流了'))));
    await _pump(tester);
    expect(find.text('模型那边限流了，正在重试 2/3'), findsOneWidget);
    expect(find.text('模型那边限流了，正在重试 1/3'), findsNothing);

    await tester.pumpWidget(_host(pending.copyWith(retry: () => const RetryNotice(attempt: 0, max: 3, delayMs: 0, reason: '模型服务器出错了', fallback: 'fast', fallbackLabel: '快速'))));
    await _pump(tester);
    expect(find.byIcon(Icons.swap_horiz_rounded), findsOneWidget);
    expect(find.textContaining('改用「快速」'), findsOneWidget);

    await tester.pumpWidget(_host(const Message(id: 'a1', role: 'assistant', blocks: [], retry: RetryNotice(attempt: 1, max: 3, delayMs: 1, reason: 'x'))));
    await _pump(tester);
    expect(find.byType(RetryLine), findsNothing); // 不在生成中：不画
  });
}
