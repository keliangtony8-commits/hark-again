// 发件箱：断线时消息是“待发送”，连上自动发；等太久/发出后没回音标“发送失败”，可重发或删除；
// 回复中途断线，连上后从服务器补全。界面上的状态行和离线条也在这里兜底。
import 'package:assistant/core/api.dart';
import 'package:assistant/core/cache.dart';
import 'package:assistant/core/chat_socket.dart';
import 'package:assistant/features/chat/chat_controller.dart';
import 'package:assistant/features/chat/chat_view.dart';
import 'package:assistant/models/message.dart';
import 'package:assistant/theme/app_theme.dart';
import 'package:assistant/theme/tokens.dart';
import 'package:fake_async/fake_async.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'chat_controller_test.dart' show FakeSocket;

class _Api implements Api {
  List<dynamic> messages = [];
  @override
  Future<dynamic> get(String path) async {
    if (path.startsWith('/api/conversations/')) return {'id': 'c1', 'messages': messages};
    if (path.startsWith('/api/conversations')) return <dynamic>[];
    return null;
  }

  @override
  dynamic noSuchMethod(Invocation i) => throw UnimplementedError();
}

(ProviderContainer, FakeSocket, _Api) _make({LinkStatus link = LinkStatus.down}) {
  final socket = FakeSocket(initial: link);
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
  test('断线时发送 → 待发送；连上后自动发出并进入生成', () async {
    final (c, socket, _) = _make();
    final ctl = c.read(chatProvider('').notifier);
    await _settle();
    expect(c.read(chatProvider('')).linkDown, true);
    ctl.send('你好');
    var s = c.read(chatProvider(''));
    expect(s.messages.single.outbox, Outbox.queued);
    expect(s.busy, true);
    expect(s.streaming, false);
    expect(socket.sent, isEmpty);

    ctl.send('第二条'); // 排队中不接受第二条
    expect(c.read(chatProvider('')).messages.length, 1);

    socket.link(LinkStatus.open);
    await _settle();
    s = c.read(chatProvider(''));
    expect(socket.sent.single['text'], '你好');
    expect(s.messages.single.outbox, Outbox.sent);
    expect(s.streaming, true);
    expect(s.linkDown, false);
  });

  test('一直连不上 → 发送失败；重发挪到末尾，删除就消失', () {
    fakeAsync((fa) {
      final (c, socket, _) = _make();
      final ctl = c.read(chatProvider('').notifier);
      ctl.send('a');
      fa.elapse(Timing.outboxGiveUp + const Duration(seconds: 1));
      final failed = c.read(chatProvider('')).messages.single;
      expect(failed.outbox, Outbox.failed);
      expect(c.read(chatProvider('')).busy, false); // 失败不挡输入框

      ctl.send('b');
      fa.elapse(Timing.outboxGiveUp + const Duration(seconds: 1));
      ctl.resend(failed.id); // b 也失败了，a 重新排队到最后
      var ms = c.read(chatProvider('')).messages;
      expect(ms.last.id, failed.id);
      expect(ms.last.outbox, Outbox.queued);

      socket.link(LinkStatus.open);
      fa.flushMicrotasks();
      expect(socket.sent.single['text'], 'a');
      ctl.discard(ms.first.id); // 删掉失败的 b
      ms = c.read(chatProvider('')).messages;
      expect(ms.map((m) => m.id), [failed.id]);
    });
  });

  test('发出后回复还没开始就断线 → 标失败；回复中途断线 → 连上后从服务器补全', () async {
    final (c, socket, api) = _make(link: LinkStatus.open);
    final ctl = c.read(chatProvider('').notifier);
    await _settle();
    ctl.send('q1');
    socket.link(LinkStatus.down);
    await _settle();
    var s = c.read(chatProvider(''));
    expect(s.streaming, false);
    expect(s.messages.single.outbox, Outbox.failed);

    ctl.discard(s.messages.single.id);
    socket.link(LinkStatus.open);
    await _settle();
    ctl.send('q2');
    socket.ctl.add({'type': 'message.start', 'conversation_id': 'c1', 'user_message_id': 'u2', 'title': 'q2'});
    socket.ctl.add({'type': 'block.delta', 'index': 0, 'text': '半截'});
    await _settle();
    socket.link(LinkStatus.down);
    await _settle();
    s = c.read(chatProvider(''));
    expect(s.streaming, false);
    expect(s.messages.any((m) => m.pending), false); // 半截回复丢掉
    expect(s.messages.single.outbox, Outbox.sent);

    api.messages = [
      {'id': 'u2', 'role': 'user', 'blocks': [{'type': 'text', 'text': 'q2'}]},
      {'id': 'm2', 'role': 'assistant', 'blocks': [{'type': 'text', 'text': '完整回复'}]},
    ];
    socket.link(LinkStatus.open);
    await _settle();
    s = c.read(chatProvider(''));
    expect(s.messages.map((m) => m.id), ['u2', 'm2']);
  });

  test('刷新对话时本机未发出的消息保留在末尾；断线点审批给出提示', () async {
    final (c, socket, api) = _make();
    final ctl = c.read(chatProvider('').notifier);
    await ctl.open('c1');
    ctl.send('还没发');
    api.messages = [
      {'id': 'u1', 'role': 'user', 'blocks': [{'type': 'text', 'text': '旧'}]},
    ];
    await ctl.sync();
    expect(socket.reconnects, 1);
    final ms = c.read(chatProvider('')).messages;
    expect(ms.map((m) => m.outbox), [Outbox.sent, Outbox.queued]);

    ctl.replyApproval('a1', true);
    expect(c.read(chatProvider('')).error, isNotNull);
  });

  testWidgets('界面：待发送/失败状态行、失败可点开菜单重发，离线条显示断线文案', (tester) async {
    final socket = FakeSocket(initial: LinkStatus.down);
    await tester.pumpWidget(ProviderScope(
      overrides: [
        chatSocketProvider.overrideWithValue(socket),
        apiProvider.overrideWithValue(_Api()),
        cacheStoreProvider.overrideWithValue(MemoryCacheStore()),
      ],
      child: MaterialApp(theme: buildTheme(Brightness.light), home: const Scaffold(body: ChatView())),
    ));
    await tester.pumpAndSettle();
    expect(find.text('连接断开 · 消息会在连上后自动发出'), findsOneWidget);

    await tester.enterText(find.byType(TextField), '离线消息');
    await tester.pumpAndSettle();
    await tester.tap(find.byIcon(Icons.arrow_upward_rounded));
    await tester.pumpAndSettle();
    expect(find.text('待发送'), findsOneWidget);

    await tester.pump(Timing.outboxGiveUp + const Duration(seconds: 1));
    await tester.pumpAndSettle();
    expect(find.text('发送失败 · 点按重发'), findsOneWidget);

    await tester.tap(find.text('发送失败 · 点按重发'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('重发'));
    await tester.pumpAndSettle();
    expect(find.text('待发送'), findsOneWidget);

    socket.link(LinkStatus.open);
    await tester.pumpAndSettle();
    expect(find.text('待发送'), findsNothing);
    expect(find.text('连接断开 · 消息会在连上后自动发出'), findsNothing);
    expect(socket.sent.single['text'], '离线消息');
  });
}
