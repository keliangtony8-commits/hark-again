// §C 并发收消息（v2.90，后端 app/message_intake.py）：回复的引用只在不紧挨着原话时画（showsQuote）；
// 本机发的消息被认领后记下服务器 id（引用 / 跳回按它对得上）；message.added（问进度的一句话、并行一路的回答）插在生成中那条前面、按 id 去重。
import 'package:assistant/core/api.dart';
import 'package:assistant/core/cache.dart';
import 'package:assistant/core/chat_socket.dart';
import 'package:assistant/features/chat/chat_controller.dart';
import 'package:assistant/models/message.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'chat_controller_test.dart' show FakeSocket;

Map<String, dynamic> _msg(String id, String role, String text, {Map<String, dynamic>? quote}) => {
      'id': id,
      'role': role,
      'blocks': [
        {'type': 'text', 'text': text}
      ],
      if (quote != null) 'reply_to': quote['id'],
      'quote': ?quote,
    };

class _Api implements Api {
  @override
  Future<dynamic> get(String path) async {
    if (path.startsWith('/api/conversations/')) return {'id': 'c1', 'messages': [_msg('u1', 'user', '写个计划'), _msg('a1', 'assistant', '好', quote: {'id': 'u1', 'role': 'user', 'text': '写个计划'})]};
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

Message _m(String id, String role, {String? quote, String? serverId}) =>
    Message(id: id, role: role, blocks: const [], quote: quote == null ? null : MessageQuote(id: quote, role: 'user', text: 'x'), serverId: serverId);

void main() {
  test('showsQuote：紧挨着（往上一串连续用户消息里有原话）不画；隔了别的回复才画；用户自己引用的一定画', () {
    final ms = [
      _m('u1', 'user'),
      _m('u2', 'user'), // 途中补充
      _m('a1', 'assistant', quote: 'u1'), // 回 u1，中间只隔用户消息 → 不画
      _m('u3', 'user'),
      _m('u4', 'user'), // 并行问的新问题
      _m('a2', 'assistant', quote: 'u4'), // 并行回答，紧挨着 → 不画
      _m('a3', 'assistant', quote: 'u3'), // 主路回答，中间隔了 a2 → 画
      _m('u5', 'user', quote: 'a1'), // 用户自己引用 → 画
      _m('a4', 'assistant'),
    ];
    expect([for (var i = 0; i < ms.length; i++) showsQuote(ms, i)], [false, false, false, false, false, false, true, true, false]);
    // 本机发的（本地 id）认领后按服务器 id 对得上
    final local = [_m('local-1', 'user', serverId: 'u9'), _m('a9', 'assistant', quote: 'u9')];
    expect(showsQuote(local, 1), false);
    expect(local[0].isId('u9') && local[0].isId('local-1') && !local[0].isId(null), true);
  });

  test('message.start 给本机提问记服务器 id；message.added 插在生成中那条前面、去重；别的对话的不收', () async {
    final socket = FakeSocket();
    final c = ProviderContainer(overrides: [
      chatSocketProvider.overrideWithValue(socket),
      apiProvider.overrideWithValue(_Api()),
      cacheStoreProvider.overrideWithValue(MemoryCacheStore()),
    ]);
    addTearDown(c.dispose);
    final ctl = c.read(chatProvider('').notifier);
    await ctl.open('c1');
    ctl.send('整理下载文件夹');
    socket.ctl.add({'type': 'message.start', 'conversation_id': 'c1', 'user_message_id': 'u2', 'title': 't', 'turn_id': 'T', 'seq': 1});
    await _settle();
    var ms = c.read(chatProvider('')).messages;
    expect(ms[2].isId('u2'), true, reason: '本机提问认领服务器 id');
    expect(ms.last.pending, true);

    ctl.send('怎么样了');
    final sent = socket.sent.last;
    expect(sent['steer'], true);
    socket.ctl.add({'type': 'turn.steered', 'conversation_id': 'c1', 'message': _msg('u3', 'user', '怎么样了'), 'client_id': sent['client_id'], 'turn_id': 'T', 'seq': 2});
    final added = {'type': 'message.added', 'conversation_id': 'c1', 'message': _msg('a2', 'assistant', '还在做', quote: {'id': 'u3', 'role': 'user', 'text': '怎么样了'})};
    socket.ctl.add(added);
    socket.ctl.add(added); // 重复推送
    socket.ctl.add({...added, 'conversation_id': 'c2', 'message': _msg('zz', 'assistant', '别的对话')});
    await _settle();
    ms = c.read(chatProvider('')).messages;
    expect(ms.map((m) => m.id).where((id) => !id.startsWith('local-')), ['u1', 'a1', 'a2', 'pending']);
    final i = ms.indexWhere((m) => m.id == 'a2');
    expect(showsQuote(ms, i), false, reason: '进度回复紧挨着“怎么样了”');

    socket.ctl.add({'type': 'message.done', 'turn_id': 'T', 'seq': 3,
      'message': _msg('a3', 'assistant', '整理好了', quote: {'id': 'u2', 'role': 'user', 'text': '整理下载文件夹'})});
    await _settle();
    ms = c.read(chatProvider('')).messages;
    expect(ms.last.id, 'a3');
    expect(showsQuote(ms, ms.length - 1), true, reason: '中间隔了进度回复：主回复画引用');
    expect(showsQuote(ms, 1), false, reason: '历史里紧挨着的回复不画');
  });
}
