// 聊天事件折叠的单元测试：模拟服务器事件流，检查消息列表是否正确拼出来。
import 'dart:async';

import 'package:assistant/core/api.dart';
import 'package:assistant/core/chat_socket.dart';
import 'package:assistant/features/chat/chat_controller.dart';
import 'package:assistant/models/block.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

/// 假长连接：默认已连上；link() 模拟断线/恢复。各测试共用。
class FakeSocket implements ChatSocket {
  FakeSocket({LinkStatus initial = LinkStatus.open}) : current = initial;
  final ctl = StreamController<Map<String, dynamic>>.broadcast();
  final _status = StreamController<LinkStatus>.broadcast();
  final sent = <Map<String, dynamic>>[];
  int reconnects = 0;
  @override
  LinkStatus current;
  @override
  Stream<LinkStatus> get status => _status.stream;
  @override
  Stream<Map<String, dynamic>> get events => ctl.stream;
  void link(LinkStatus s) {
    current = s;
    _status.add(s);
  }

  @override
  bool send(Map<String, dynamic> payload) {
    if (current != LinkStatus.open) return false;
    sent.add(payload);
    return true;
  }

  @override
  void reconnectNow() => reconnects++;
  @override
  void close() {
    ctl.close();
    _status.close();
  }
}

class FakeApi implements Api {
  @override
  Future<dynamic> get(String path) async => path.startsWith('/api/conversations') ? <dynamic>[] : null;
  @override
  dynamic noSuchMethod(Invocation i) => throw UnimplementedError();
}

void main() {
  test('folds a streamed turn into messages', () async {
    final socket = FakeSocket();
    final c = ProviderContainer(overrides: [
      chatSocketProvider.overrideWithValue(socket),
      apiProvider.overrideWithValue(FakeApi()),
    ]);
    addTearDown(c.dispose);
    final ctl = c.read(chatProvider('').notifier);

    ctl.send('你好');
    expect(socket.sent.single['text'], '你好');
    expect(c.read(chatProvider('')).streaming, true);

    for (final e in [
      {'type': 'message.start', 'conversation_id': 'c1', 'user_message_id': 'u1', 'title': '你好'},
      {'type': 'tool.status', 'id': 't1', 'name': 'web_search', 'label': '正在搜索', 'state': 'running'},
      {'type': 'block.start', 'index': 0, 'block': {'type': 'text', 'text': ''}},
      {'type': 'block.delta', 'index': 0, 'text': '你'},
      {'type': 'block.delta', 'index': 0, 'text': '好！'},
      {'type': 'block.start', 'index': 1, 'block': {'type': 'approval', 'id': 'a1', 'title': '提交', 'detail': 'git push', 'state': 'pending'}},
      {'type': 'block.update', 'index': 1, 'block': {'type': 'approval', 'id': 'a1', 'title': '提交', 'detail': 'git push', 'state': 'approved'}},
    ]) {
      socket.ctl.add(e);
    }
    await Future<void>.delayed(Duration.zero);

    var s = c.read(chatProvider(''));
    expect(s.activeId, 'c1');
    final pending = s.messages.last;
    expect(pending.pending, true);
    expect((pending.blocks[0] as TextBlock).text, '你好！');
    expect((pending.blocks[1] as ApprovalBlock).state, 'approved');
    expect(pending.tools.single.running, true);

    socket.ctl.add({
      'type': 'message.done',
      'message': {'id': 'm1', 'role': 'assistant', 'blocks': [{'type': 'text', 'text': '你好！'}, {'type': 'weird_future_block'}]}
    });
    await Future<void>.delayed(Duration.zero);
    s = c.read(chatProvider(''));
    expect(s.streaming, false);
    expect(s.messages.length, 2);
    expect(s.messages.last.blocks.last, isA<UnknownBlock>()); // 未知块不崩
  });

  test('搜索带编码后的 q 和项目 id；改名/置顶后刷新列表', () async {
    final api = RecordingApi();
    final c = ProviderContainer(overrides: [
      chatSocketProvider.overrideWithValue(FakeSocket()),
      apiProvider.overrideWithValue(api),
    ]);
    addTearDown(c.dispose);
    final ctl = c.read(chatProvider('p1').notifier);
    await Future<void>.delayed(Duration.zero); // 让 build 里的首次列表加载先跑完
    final r = await ctl.search(' 猫 & 狗 ');
    expect(r.single.snippet, '…猫…');
    expect(Uri.parse(api.gets.last).queryParameters, {'project_id': 'p1', 'q': '猫 & 狗'});
    await ctl.setPinned('c1', true);
    expect(api.patches.single.$1, '/api/conversations/c1');
    expect(api.patches.single.$2, {'pinned': true});
    expect(Uri.parse(api.gets.last).queryParameters, {'project_id': 'p1'});
  });
}

class RecordingApi implements Api {
  final gets = <String>[];
  final patches = <(String, Object)>[];
  @override
  Future<dynamic> get(String path) async {
    gets.add(path);
    return [
      {'id': 'c1', 'title': 't', 'snippet': '…猫…'}
    ];
  }

  @override
  Future<dynamic> patch(String path, Object body) async {
    patches.add((path, body));
    return {'id': 'c1', 'title': 't', 'pinned': true};
  }

  @override
  dynamic noSuchMethod(Invocation i) => throw UnimplementedError();
}
