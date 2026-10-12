// 断线续传（v1.61，服务器 live_turns）：回复中途断线不丢半截，连上后按 seq 续传、去重；
// 快照替换；服务器没这轮了以 GET 为准；打开对话接上别处还在写的回答；发送后回复前断线、服务器其实在答 → 改回已发出；
// 重连退避带抖动、封顶。
import 'package:assistant/core/api.dart';
import 'package:assistant/core/chat_socket.dart';
import 'package:assistant/features/chat/chat_controller.dart';
import 'package:assistant/models/block.dart';
import 'package:assistant/models/message.dart';
import 'package:assistant/theme/tokens.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'chat_controller_test.dart' show FakeSocket;

class _Api implements Api {
  List<dynamic> messages = [];
  int gets = 0;
  @override
  Future<dynamic> get(String path) async {
    if (path.startsWith('/api/conversations/')) {
      gets++;
      return {'id': 'c1', 'messages': messages};
    }
    return <dynamic>[];
  }

  @override
  dynamic noSuchMethod(Invocation i) => throw UnimplementedError();
}

Future<void> _settle() => Future<void>.delayed(const Duration(milliseconds: 10));

(ProviderContainer, FakeSocket, _Api) _make() {
  final socket = FakeSocket();
  final api = _Api();
  final c = ProviderContainer(overrides: [
    chatSocketProvider.overrideWithValue(socket),
    apiProvider.overrideWithValue(api),
  ]);
  c.listen(chatProvider(''), (_, _) {});
  addTearDown(c.dispose);
  return (c, socket, api);
}

Map<String, dynamic> _ev(int seq, Map<String, dynamic> e) => {...e, 'turn_id': 't1', 'seq': seq};

String _text(Message m) => m.blocks.whereType<TextBlock>().map((b) => b.text).join();

void main() {
  test('回复中途断线：半截留着、仍在生成；连上后 turn.resume 带游标，补发的重复事件被丢掉', () async {
    final (c, socket, _) = _make();
    final ctl = c.read(chatProvider('').notifier);
    await _settle();
    ctl.send('写两段');
    socket.ctl.add(_ev(1, {'type': 'message.start', 'conversation_id': 'c1', 'user_message_id': 'u1', 'title': 't'}));
    socket.ctl.add(_ev(2, {'type': 'block.start', 'index': 0, 'block': {'type': 'text', 'text': ''}}));
    socket.ctl.add(_ev(3, {'type': 'block.delta', 'index': 0, 'text': '第一段'}));
    await _settle();
    socket.link(LinkStatus.down);
    await _settle();
    var s = c.read(chatProvider(''));
    expect(s.streaming, true);
    expect(_text(s.messages.last), '第一段');
    expect(s.messages.last.pending, true);

    socket.link(LinkStatus.open);
    await _settle();
    expect(socket.resumes.last, {'type': 'turn.resume', 'turn_id': 't1', 'conversation_id': 'c1', 'after': 3});
    socket.ctl.add({'type': 'turn.resumed', 'turn_id': 't1', 'conversation_id': 'c1', 'live': true, 'ended': false, 'seq': 4, 'gap': false});
    socket.ctl.add(_ev(3, {'type': 'block.delta', 'index': 0, 'text': '第一段'})); // 重复：丢
    socket.ctl.add(_ev(4, {'type': 'block.delta', 'index': 0, 'text': '第二段'}));
    socket.ctl.add(_ev(4, {'type': 'block.delta', 'index': 0, 'text': '第二段'})); // 重复：丢
    await _settle();
    s = c.read(chatProvider(''));
    expect(_text(s.messages.last), '第一段第二段');
    socket.ctl.add(_ev(5, {
      'type': 'message.done',
      'message': {'id': 'm1', 'role': 'assistant', 'blocks': [{'type': 'text', 'text': '第一段第二段'}]}
    }));
    await _settle();
    s = c.read(chatProvider(''));
    expect(s.streaming, false);
    expect(s.messages.map((m) => m.id).last, 'm1');
    expect(s.messages.where((m) => m.pending), isEmpty);
  });

  test('游标太旧 → 快照整份替换；服务器没这轮了 → 丢半截、以 GET 为准', () async {
    final (c, socket, api) = _make();
    final ctl = c.read(chatProvider('').notifier);
    await _settle();
    ctl.send('长文');
    socket.ctl.add(_ev(1, {'type': 'message.start', 'conversation_id': 'c1', 'user_message_id': 'u1', 'title': 't'}));
    socket.ctl.add(_ev(2, {'type': 'block.start', 'index': 0, 'block': {'type': 'text', 'text': '甲'}}));
    await _settle();
    socket.link(LinkStatus.down);
    socket.link(LinkStatus.open);
    await _settle();
    socket.ctl.add({'type': 'turn.resumed', 'turn_id': 't1', 'conversation_id': 'c1', 'live': true, 'ended': false, 'seq': 90, 'gap': true});
    socket.ctl.add({
      'type': 'turn.snapshot', 'turn_id': 't1', 'seq': 90, 'conversation_id': 'c1',
      'message': {
        'blocks': [{'type': 'text', 'text': '甲乙丙'}],
        'steps': [{'id': 's1', 'tool': 'web_search', 'title': '搜索', 'detail': 'x', 'state': 'done', 'at': '2026-10-12T14:00:00Z'}]
      }
    });
    socket.ctl.add(_ev(90, {'type': 'block.delta', 'index': 0, 'text': '重复'})); // 快照已含：丢
    socket.ctl.add(_ev(91, {'type': 'block.delta', 'index': 0, 'text': '丁'}));
    await _settle();
    var s = c.read(chatProvider(''));
    expect(s.messages.where((m) => m.pending).length, 1);
    expect(_text(s.messages.last), '甲乙丙丁');
    expect(s.messages.last.steps.single.id, 's1');

    // 再断一次，这回服务器重启了：没这轮
    socket.link(LinkStatus.down);
    socket.link(LinkStatus.open);
    await _settle();
    expect(socket.resumes.last['after'], 91);
    api.messages = [
      {'id': 'u1', 'role': 'user', 'blocks': [{'type': 'text', 'text': '长文'}]},
      {'id': 'm9', 'role': 'assistant', 'status': 'interrupted', 'blocks': [{'type': 'text', 'text': '甲乙丙丁'}]},
    ];
    socket.ctl.add({'type': 'turn.resumed', 'turn_id': 't1', 'conversation_id': 'c1', 'live': false});
    await _settle();
    s = c.read(chatProvider(''));
    expect(s.streaming, false);
    expect(s.messages.map((m) => m.id), ['u1', 'm9']);
    expect(s.messages.last.interrupted, true);
  });

  test('打开对话：问一次有没有在写的回答；有就接上（从 message.start 起），被替换的旧回复撤掉', () async {
    final (c, socket, api) = _make();
    api.messages = [
      {'id': 'u1', 'role': 'user', 'blocks': [{'type': 'text', 'text': '问'}]},
      {'id': 'm0', 'role': 'assistant', 'blocks': [{'type': 'text', 'text': '旧答'}]},
    ];
    final ctl = c.read(chatProvider('').notifier);
    await ctl.open('c1');
    expect(socket.resumes.single, {'type': 'turn.resume', 'conversation_id': 'c1'});
    socket.ctl.add({'type': 'turn.resumed', 'turn_id': 't1', 'conversation_id': 'c1', 'live': true, 'ended': false, 'seq': 2, 'gap': false});
    await _settle();
    expect(c.read(chatProvider('')).streaming, true);
    socket.ctl.add(_ev(1, {'type': 'message.start', 'conversation_id': 'c1', 'user_message_id': 'u1', 'title': 't', 'replaced': ['m0']}));
    socket.ctl.add(_ev(2, {'type': 'block.start', 'index': 0, 'block': {'type': 'text', 'text': '新答'}}));
    await _settle();
    final s = c.read(chatProvider(''));
    expect(s.messages.map((m) => m.id), ['u1', 'pending']);
    expect(_text(s.messages.last), '新答');
    expect(s.canStop, true); // 别处发起的也能停（服务器按 conversation_id 找）

    // 没有在写的：什么都不变
    socket.ctl.add({'type': 'turn.resumed', 'turn_id': null, 'conversation_id': 'c2', 'live': false});
    await _settle();
    expect(c.read(chatProvider('')).streaming, true);
  });

  test('发出后回复前断线：先标失败；连上后服务器说正在答 → 改回已发出并接着收', () async {
    final (c, socket, _) = _make();
    final ctl = c.read(chatProvider('').notifier);
    await ctl.open('c1');
    ctl.send('在吗');
    socket.link(LinkStatus.down);
    await _settle();
    expect(c.read(chatProvider('')).messages.last.outbox, Outbox.failed);
    socket.link(LinkStatus.open);
    await _settle();
    expect(socket.resumes.last, {'type': 'turn.resume', 'conversation_id': 'c1'});
    socket.ctl.add({'type': 'turn.resumed', 'turn_id': 't9', 'conversation_id': 'c1', 'live': true, 'ended': false, 'seq': 1, 'gap': false});
    socket.ctl.add({'type': 'message.start', 'conversation_id': 'c1', 'user_message_id': 'u7', 'title': 't', 'turn_id': 't9', 'seq': 1});
    await _settle();
    final s = c.read(chatProvider(''));
    expect(s.streaming, true);
    expect(s.messages.lastWhere((m) => m.isUser).outbox, Outbox.sent);
    expect(s.messages.last.pending, true);
  });

  test('重连退避：1 秒起翻倍、封顶 10 秒，乘 0.5–1 抖动', () {
    expect(reconnectDelay(0, jitter: 1), Timing.socketBackoffMin);
    expect(reconnectDelay(0, jitter: 0), Timing.socketBackoffMin * 0.5);
    expect(reconnectDelay(2, jitter: 1), const Duration(seconds: 4));
    expect(reconnectDelay(9, jitter: 1), Timing.socketBackoffMax);
    expect(reconnectDelay(60, jitter: 0), Timing.socketBackoffMax * 0.5);
  });
}
