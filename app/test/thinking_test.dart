// 推理模型的思考过程：WS thinking.delta 累积到生成中的占位消息（只留尾部），界面显示“思考中”小卡露出最新两行；
// 正文一来换成回复卡，message.done 换上的正式消息里没有思考内容（服务器不存）。
import 'package:assistant/core/api.dart';
import 'package:assistant/core/cache.dart';
import 'package:assistant/core/chat_socket.dart';
import 'package:assistant/features/chat/chat_controller.dart';
import 'package:assistant/features/chat/message_view.dart';
import 'package:assistant/features/chat/thought_view.dart';
import 'package:assistant/models/message.dart';
import 'package:assistant/theme/app_theme.dart';
import 'package:assistant/ui/kit.dart';
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

Widget _host(Message m) => ProviderScope(
      child: MaterialApp(
        theme: buildTheme(Brightness.light),
        home: Scaffold(body: SizedBox(width: 400, child: MessageView(m))),
      ),
    );

void main() {
  test('think() 累积、超长只留尾部', () {
    var m = const Message(id: 'pending', role: 'assistant', blocks: [], pending: true);
    m = m.think('先').think('想');
    expect(m.thought, '先想');
    m = m.think('x' * (Message.thoughtKeep + 50));
    expect(m.thought.length, Message.thoughtKeep);
    expect(m.thought.endsWith('x'), true);
    expect(m.copyWith(pending: false).thought, m.thought); // copyWith 不丢
  });

  test('thinking.delta → 占位消息带思考；message.done 后没有', () async {
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
    ctl.send('难题');
    socket.ctl.add({'type': 'message.start', 'conversation_id': 'c1', 'user_message_id': 'u1', 'title': 't'});
    socket.ctl.add({'type': 'thinking.delta', 'text': '用户想要'});
    socket.ctl.add({'type': 'thinking.delta', 'text': '一个答案'});
    await _settle();
    var last = c.read(chatProvider('')).messages.last;
    expect(last.pending, true);
    expect(last.thought, '用户想要一个答案');

    socket.ctl.add({
      'type': 'message.done',
      'message': {
        'id': 'a1', 'role': 'assistant',
        'blocks': [{'type': 'text', 'text': '答案'}]
      }
    });
    await _settle();
    last = c.read(chatProvider('')).messages.last;
    expect(last.pending, false);
    expect(last.id, 'a1');
    expect(last.thought, '用户想要一个答案'); // v0.67：本次会话里接到正式消息上，回复上方可展开
    expect(last.thinkTime, isNotNull);
  });

  test('thinkDuration / thinkTime', () {
    expect(thinkDuration(const Duration(milliseconds: 300)), '1 秒');
    expect(thinkDuration(const Duration(milliseconds: 8400)), '8 秒');
    expect(thinkDuration(const Duration(seconds: 65)), '1 分 5 秒');
    final t0 = DateTime(2026, 10, 11, 17);
    final m = const Message(id: 'p', role: 'assistant', blocks: [], pending: true)
        .think('a', at: t0)
        .think('b', at: t0.add(const Duration(seconds: 12)));
    expect(m.thinkTime, const Duration(seconds: 12));
    const plain = Message(id: 'x', role: 'assistant', blocks: []);
    expect(plain.withThoughtOf(const Message(id: 'p', role: 'assistant', blocks: [])).thought, '');
    expect(plain.withThoughtOf(m).thinkFrom, t0);
  });

  testWidgets('回复上方“已思考 12 秒”：点开看全部思考，再点收起', (t) async {
    t.view.devicePixelRatio = 1;
    addTearDown(t.view.reset);
    final t0 = DateTime(2026, 10, 11, 17);
    final done = Message.fromJson({
      'id': 'a1', 'role': 'assistant',
      'blocks': [{'type': 'text', 'text': '答案'}]
    }).withThoughtOf(const Message(id: 'p', role: 'assistant', blocks: [], pending: true)
        .think('先查天气\n再回答', at: t0)
        .think('。', at: t0.add(const Duration(seconds: 12))));
    await t.pumpWidget(_host(done));
    await t.pumpAndSettle();
    expect(find.text('已思考 12 秒'), findsOneWidget);
    expect(find.textContaining('先查天气'), findsNothing);
    await t.tap(find.text('已思考 12 秒'));
    await t.pumpAndSettle();
    expect(find.textContaining('先查天气'), findsOneWidget);
    await t.tap(find.text('已思考 12 秒'));
    await t.pumpAndSettle();
    expect(find.textContaining('先查天气'), findsNothing);
    // 没思考过的回复没有这一行
    await t.pumpWidget(_host(Message.fromJson({'id': 'a2', 'role': 'assistant', 'blocks': [{'type': 'text', 'text': '答'}]})));
    await t.pumpAndSettle();
    expect(find.textContaining('已思考'), findsNothing);
  });

  testWidgets('没有思考 = 三个点；有思考 = “思考中”小卡露出最新内容；出正文后换成回复卡', (t) async {
    t.view.devicePixelRatio = 1;
    addTearDown(t.view.reset);
    const pending = Message(id: 'pending', role: 'assistant', blocks: [], pending: true);
    await t.pumpWidget(_host(pending));
    expect(find.byKey(const ValueKey('thinking')), findsOneWidget);
    expect(find.text('思考中'), findsNothing);

    await t.pumpWidget(_host(pending.think('第一步\n\n第二步：查天气')));
    await t.pump(const Duration(milliseconds: 400));
    expect(find.text('思考中'), findsOneWidget);
    expect(find.byType(TailText), findsOneWidget);
    expect(find.text('第一步 第二步：查天气'), findsOneWidget); // 换行压成空格
    // 很长的思考：固定两行高，不撑开
    await t.pumpWidget(_host(pending.think('很长的思考' * 200)));
    await t.pump(const Duration(milliseconds: 400));
    final h = t.getSize(find.byType(TailText)).height;
    expect(h, lessThan(60));
    expect(t.takeException(), isNull);

    await t.pumpWidget(_host(pending.think('想好了').copyWith(blocks: const [])));
    await t.pumpWidget(_host(Message.fromJson({
      'id': 'a1', 'role': 'assistant',
      'blocks': [{'type': 'text', 'text': '答案'}]
    })));
    await t.pump(const Duration(milliseconds: 400));
    expect(find.text('思考中'), findsNothing);
    await t.pumpWidget(const SizedBox()); // 卸掉计时器
  });
}
