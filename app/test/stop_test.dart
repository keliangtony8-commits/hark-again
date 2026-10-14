// 停止生成：生成中发 message.cancel、停止键置灰防连点；服务器回半截回复（stopped）或 message.stopped 才收尾；
// 半截回复带“已停止”并能重新生成；断线时不排队只提示；界面上发送键在生成中换成停止键。
import 'package:assistant/core/api.dart';
import 'package:assistant/core/cache.dart';
import 'package:assistant/core/chat_socket.dart';
import 'package:assistant/features/chat/chat_controller.dart';
import 'package:assistant/features/chat/chat_view.dart';
import 'package:assistant/models/message.dart';
import 'package:assistant/theme/app_theme.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'chat_controller_test.dart' show FakeSocket;

Map<String, dynamic> _msg(String id, String role, String text, {String? status}) => {
      'id': id,
      'role': role,
      'blocks': [
        {'type': 'text', 'text': text}
      ],
      'status': ?status,
    };

class _Api implements Api {
  List<dynamic> messages = [_msg('u1', 'user', '写首诗'), _msg('a1', 'assistant', '春眠不觉晓')];
  @override
  Future<dynamic> get(String path) async {
    if (path.startsWith('/api/conversations/')) return {'id': 'c1', 'messages': messages};
    if (path.startsWith('/api/conversations')) return <dynamic>[];
    return null;
  }

  @override
  dynamic noSuchMethod(Invocation i) => throw UnimplementedError();
}

(ProviderContainer, FakeSocket, _Api) _make() {
  final socket = FakeSocket();
  final api = _Api();
  final c = ProviderContainer(overrides: [
    chatSocketProvider.overrideWithValue(socket),
    apiProvider.overrideWithValue(api),
    cacheStoreProvider.overrideWithValue(MemoryCacheStore()),
  ]);
  addTearDown(c.dispose);
  return (c, socket, api);
}

Future<void> _settle() async {
  for (var i = 0; i < 5; i++) {
    await Future<void>.delayed(Duration.zero);
  }
}

void main() {
  test('Message.fromJson 读 status=stopped；没有 status 就是完整回复', () {
    expect(Message.fromJson(_msg('a', 'assistant', 'x', status: 'stopped')).stopped, true);
    expect(Message.fromJson(_msg('a', 'assistant', 'x')).stopped, false);
  });

  test('说到一半停止：发 cancel → 置灰 → 服务器回半截回复（stopped）才收尾', () async {
    final (c, socket, _) = _make();
    final ctl = c.read(chatProvider('').notifier);
    await ctl.open('c1');
    ctl.send('再写一首');
    socket.ctl.add({'type': 'message.start', 'conversation_id': 'c1', 'user_message_id': 'u2', 'title': 't'});
    socket.ctl.add({'type': 'block.start', 'index': 0, 'block': {'type': 'text', 'text': '床前'}});
    await _settle();
    expect(c.read(chatProvider('')).canStop, true);

    ctl.stop();
    ctl.stop(); // 连点只发一次
    var s = c.read(chatProvider(''));
    expect(socket.sent.where((e) => e['type'] == 'message.cancel').toList(), [
      {'type': 'message.cancel', 'conversation_id': 'c1'}
    ]);
    expect(s.stopping, true);
    expect(s.canStop, false);
    expect(s.streaming, true); // 不在本地先砍，等服务器

    socket.ctl.add({'type': 'message.done', 'message': _msg('a2', 'assistant', '床前', status: 'stopped')});
    await _settle();
    s = c.read(chatProvider(''));
    expect(s.streaming, false);
    expect(s.stopping, false);
    expect(s.messages.last.stopped, true);
    expect(s.canRegenerate, true); // 半截的可以重新生成补全
  });

  test('还没吐字就停：message.stopped 撤掉思考占位，用户消息留着可重试', () async {
    final (c, socket, _) = _make();
    final ctl = c.read(chatProvider('').notifier);
    await ctl.open('c1');
    ctl.send('再写一首');
    socket.ctl.add({'type': 'message.start', 'conversation_id': 'c1', 'user_message_id': 'u2', 'title': 't'});
    await _settle();
    ctl.stop();
    socket.ctl.add({'type': 'message.stopped', 'conversation_id': 'c1'});
    await _settle();
    final s = c.read(chatProvider(''));
    expect(s.streaming, false);
    expect(s.messages.any((m) => m.pending), false);
    expect(s.messages.last.isUser, true);
    expect(s.canRegenerate, true);
    ctl.regenerate();
    expect(socket.sent.last, {'type': 'message.regenerate', 'conversation_id': 'c1'});
  });

  test('停止请求发出后断线：stopping 随这一轮一起清掉；线断时点停止只提示', () async {
    final (c, socket, _) = _make();
    final ctl = c.read(chatProvider('').notifier);
    await ctl.open('c1');
    ctl.send('再写一首');
    socket.ctl.add({'type': 'message.start', 'conversation_id': 'c1', 'user_message_id': 'u2', 'title': 't'});
    await _settle();
    ctl.stop();
    socket.link(LinkStatus.down);
    await _settle();
    var s = c.read(chatProvider(''));
    expect(s.streaming, false);
    expect(s.stopping, false);

    socket.link(LinkStatus.open);
    await _settle();
    ctl.send('第三首');
    socket.link(LinkStatus.down); // 发出后、回复前断线
    await _settle();
    expect(c.read(chatProvider('')).canStop, false); // 不在生成了，停止无事可做
    final before = socket.sent.length;
    ctl.stop();
    expect(socket.sent.length, before);
  });

  testWidgets('界面：生成中发送键换成停止键，点了置灰；停下的回复标“已停止”', (tester) async {
    final socket = FakeSocket();
    final api = _Api();
    final container = ProviderContainer(overrides: [
      chatSocketProvider.overrideWithValue(socket),
      apiProvider.overrideWithValue(api),
      cacheStoreProvider.overrideWithValue(MemoryCacheStore()),
    ]);
    addTearDown(container.dispose);
    await tester.pumpWidget(UncontrolledProviderScope(
      container: container,
      child: MaterialApp(theme: buildTheme(Brightness.light), home: const Scaffold(body: ChatView())),
    ));
    final ctl = container.read(chatProvider('').notifier);
    await ctl.open('c1');
    await tester.pumpAndSettle();
    expect(find.bySemanticsLabel('停止生成'), findsNothing);

    ctl.send('再写一首');
    socket.ctl.add({'type': 'message.start', 'conversation_id': 'c1', 'user_message_id': 'u2', 'title': 't'});
    socket.ctl.add({'type': 'block.start', 'index': 0, 'block': {'type': 'text', 'text': '床前'}});
    await tester.pumpAndSettle();
    expect(find.bySemanticsLabel('停止生成'), findsOneWidget);
    await tester.tap(find.bySemanticsLabel('停止生成'));
    await tester.pumpAndSettle();
    expect(socket.sent.last['type'], 'message.cancel');
    expect(container.read(chatProvider('')).stopping, true);

    socket.ctl.add({'type': 'message.done', 'message': _msg('a2', 'assistant', '床前', status: 'stopped')});
    await tester.pumpAndSettle();
    expect(find.bySemanticsLabel('停止生成'), findsNothing);
    expect(find.text('已停止'), findsOneWidget);
    await tester.longPress(find.text('床前'));
    await tester.pumpAndSettle();
    expect(find.text('重新生成'), findsOneWidget);
  });
}
