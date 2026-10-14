// 生成中发消息（v1.83 steering → v2.90 message_intake）：生成中照常发 = user.message 带 steer + client_id，气泡插在生成中那条前面；
// turn.steered 认领本地气泡（不再另标字）；别的设备发的按 id 补上；排成下一轮时 message.start 带回 client_id → 挪到末尾；
// 快照以服务器为准；线不通标失败；界面：生成中有字时停止钮换成发送钮，清空后回到停止钮。
import 'package:assistant/core/api.dart';
import 'package:assistant/core/cache.dart';
import 'package:assistant/core/chat_socket.dart';
import 'package:assistant/features/chat/chat_controller.dart';
import 'package:assistant/features/chat/chat_view.dart';
import 'package:assistant/models/block.dart';
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
  List<dynamic> messages = [_msg('u1', 'user', '写个计划'), _msg('a1', 'assistant', '好')];
  @override
  Future<dynamic> get(String path) async {
    if (path.startsWith('/api/conversations/')) return {'id': 'c1', 'messages': messages};
    if (path.startsWith('/api/conversations')) return <dynamic>[];
    return null;
  }

  @override
  dynamic noSuchMethod(Invocation i) => throw UnimplementedError();
}

(ProviderContainer, FakeSocket) _make() {
  final socket = FakeSocket();
  final c = ProviderContainer(overrides: [
    chatSocketProvider.overrideWithValue(socket),
    apiProvider.overrideWithValue(_Api()),
    cacheStoreProvider.overrideWithValue(MemoryCacheStore()),
  ]);
  addTearDown(c.dispose);
  return (c, socket);
}

Future<void> _settle() async {
  for (var i = 0; i < 5; i++) {
    await Future<void>.delayed(Duration.zero);
  }
}

String _text(Message m) => m.blocks.whereType<TextBlock>().map((b) => b.text).join();

Future<ChatController> _streaming(ProviderContainer c, FakeSocket socket) async {
  final ctl = c.read(chatProvider('').notifier);
  await ctl.open('c1');
  ctl.send('再细一点');
  socket.ctl.add({'type': 'message.start', 'conversation_id': 'c1', 'user_message_id': 'u2', 'title': 't', 'turn_id': 'T', 'seq': 1});
  socket.ctl.add({'type': 'block.start', 'index': 0, 'block': {'type': 'text', 'text': '第一周'}, 'turn_id': 'T', 'seq': 2});
  await _settle();
  return ctl;
}

void main() {
  test('Message.fromJson：用户消息 status=steer 是途中补充；beforePending 插在生成中那条前面', () {
    expect(Message.fromJson(_msg('u', 'user', 'x', status: 'steer')).steer, true);
    expect(Message.fromJson(_msg('a', 'assistant', 'x', status: 'steer')).steer, false);
    expect(Message.fromJson(_msg('u', 'user', 'x')).steer, false);
    const a = Message(id: 'a', role: 'user', blocks: []);
    const p = Message(id: 'p', role: 'assistant', blocks: [], pending: true);
    const m = Message(id: 'm', role: 'user', blocks: []);
    expect(beforePending([a, p], m).map((x) => x.id), ['a', 'm', 'p']);
    expect(beforePending([a], m).map((x) => x.id), ['a', 'm']);
  });

  test('生成中补一句：发 steer + client_id，插在生成中那条前面；turn.steered 认领', () async {
    final (c, socket) = _make();
    final ctl = await _streaming(c, socket);
    expect(c.read(chatProvider('')).canSteer, true);
    ctl.send('  按周排  ');
    final sent = socket.sent.last;
    expect(sent['type'], 'user.message');
    expect(sent['steer'], true);
    expect(sent['text'], '按周排');
    expect(sent['conversation_id'], 'c1');
    final local = sent['client_id'] as String;
    var ms = c.read(chatProvider('')).messages;
    expect(ms.length, 5);
    expect(ms[3].id, local);
    expect(ms[3].steer, true);
    expect(ms.last.pending, true);
    expect(c.read(chatProvider('')).streaming, true);

    socket.ctl.add({'type': 'turn.steered', 'conversation_id': 'c1', 'client_id': local, 'turn_id': 'T', 'seq': 3,
      'message': _msg('s1', 'user', '按周排', status: 'steer')});
    await _settle();
    ms = c.read(chatProvider('')).messages;
    expect(ms.length, 5, reason: '认领，不重复');
    expect(ms[3].steer, true);
    expect(ms[3].unsent, false);

    socket.ctl.add({'type': 'message.done', 'turn_id': 'T', 'seq': 4, 'message': _msg('a2', 'assistant', '第一周……')});
    await _settle();
    ms = c.read(chatProvider('')).messages;
    expect(ms.map(_text).toList(), ['写个计划', '好', '再细一点', '按周排', '第一周……']);
  });

  test('生成中带附件补充（v1.93）：附件按线格式发出（上传 / 工作区分开），气泡带附件块；只发附件也行', () async {
    final (c, socket) = _make();
    final ctl = await _streaming(c, socket);
    const img = FileBlock(source: 'upload', id: 'up1', name: '红.png', mime: 'image/png', size: 10);
    const doc = FileBlock(source: 'project', id: 'plan.md', name: 'plan.md', mime: 'text/markdown', size: 5, projectId: 'me');
    ctl.send(' 参考这个 ', files: [img, doc]);
    var sent = socket.sent.last;
    expect(sent['steer'], true);
    expect(sent['text'], '参考这个');
    expect(sent['attachments'], ['up1']);
    expect(sent['project_files'], ['plan.md']);
    var ms = c.read(chatProvider('')).messages;
    final bubble = ms[ms.length - 2];
    expect(bubble.steer, true);
    expect(bubble.blocks.whereType<FileBlock>().map((f) => f.id), ['up1', 'plan.md']);
    expect(ms.last.pending, true);

    ctl.send('', files: [img]);
    sent = socket.sent.last;
    expect(sent['steer'], true);
    expect(sent['text'], '');
    expect(sent['attachments'], ['up1']);
    ms = c.read(chatProvider('')).messages;
    expect(ms[ms.length - 2].blocks.single, isA<FileBlock>());
    expect(ms.last.pending, true);
  });

  test('别的设备补充的：按 id 补在生成中那条前面；快照里的也补上、本机未认领的乐观气泡以快照为准', () async {
    final (c, socket) = _make();
    await _streaming(c, socket);
    socket.ctl.add({'type': 'turn.steered', 'conversation_id': 'c1', 'turn_id': 'T', 'seq': 3,
      'message': _msg('s9', 'user', '别的手机说的', status: 'steer')});
    await _settle();
    var ms = c.read(chatProvider('')).messages;
    expect(ms[ms.length - 2].id, 's9');
    expect(ms.last.pending, true);

    c.read(chatProvider('').notifier).send('本机没认领的');
    socket.ctl.add({'type': 'turn.snapshot', 'conversation_id': 'c1', 'turn_id': 'T', 'seq': 9,
      'message': {'blocks': [{'type': 'text', 'text': '第一周第二周'}], 'steps': []},
      'steered': [_msg('s9', 'user', '别的手机说的', status: 'steer'), _msg('s10', 'user', '本机没认领的', status: 'steer')]});
    await _settle();
    ms = c.read(chatProvider('')).messages;
    expect(ms.map((m) => m.id).where((id) => id.startsWith('s')).toList(), ['s9', 's10']);
    expect(ms.where((m) => m.id.startsWith(ChatController.localPrefix) && m.steer), isEmpty);
    expect(ms.last.pending, true);
  });

  test('插不进（刚好答完）排成下一轮：message.start 带回 client_id → 挪到末尾、不再标补充', () async {
    final (c, socket) = _make();
    final ctl = await _streaming(c, socket);
    ctl.send('顺便天气');
    final local = socket.sent.last['client_id'] as String;
    socket.ctl.add({'type': 'message.done', 'turn_id': 'T', 'seq': 3, 'message': _msg('a2', 'assistant', '计划好了')});
    socket.ctl.add({'type': 'message.start', 'conversation_id': 'c1', 'user_message_id': 'u3', 'client_id': local, 'turn_id': 'T2', 'seq': 1});
    await _settle();
    final ms = c.read(chatProvider('')).messages;
    expect(ms[ms.length - 2].id, local);
    expect(ms[ms.length - 2].steer, false);
    expect(ms.last.pending, true);
    expect(_text(ms[ms.length - 3]), '计划好了');
  });

  test('线不通：补充标失败；不在生成中照旧排队', () async {
    final (c, socket) = _make();
    final ctl = await _streaming(c, socket);
    socket.current = LinkStatus.down; // 只改线况、不推状态事件：模拟“刚好断了还没察觉”
    ctl.send('补一句');
    final m = c.read(chatProvider('')).messages.firstWhere((m) => _text(m) == '补一句');
    expect(m.outbox, Outbox.failed);
    expect(m.steer, false);
  });

  testWidgets('界面：生成中有字 → 发送钮；清空 → 停止钮；途中发的气泡不另标字', (tester) async {
    final socket = FakeSocket();
    final container = ProviderContainer(overrides: [
      chatSocketProvider.overrideWithValue(socket),
      apiProvider.overrideWithValue(_Api()),
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
    ctl.send('再细一点');
    socket.ctl.add({'type': 'message.start', 'conversation_id': 'c1', 'user_message_id': 'u2', 'title': 't', 'turn_id': 'T', 'seq': 1});
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 400));
    expect(find.bySemanticsLabel('停止生成'), findsOneWidget);

    await tester.enterText(find.byType(TextField), '按周排');
    await tester.pump();
    await tester.pump(const Duration(seconds: 1));
    expect(find.bySemanticsLabel('停止生成'), findsNothing);
    expect(find.bySemanticsLabel('发送'), findsOneWidget, reason: 'v2.90 生成中照常发送，服务器判断是补充还是另一件事');
    await tester.tap(find.bySemanticsLabel('发送'));
    await tester.pump(const Duration(milliseconds: 400));
    expect(socket.sent.last['steer'], true);
    expect(find.bySemanticsLabel('停止生成'), findsOneWidget, reason: '发出后输入框清空，回到停止钮');
    expect(find.text('回答途中补充'), findsNothing, reason: 'v2.90 不再给途中发的消息另标字');

    socket.ctl.add({'type': 'message.done', 'turn_id': 'T', 'seq': 3, 'message': _msg('a2', 'assistant', '好的')});
    await tester.pumpAndSettle();
  });
}
