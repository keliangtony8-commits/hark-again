// 自动标题（v1.67，服务器 conversation_title）：conversation.title 事件到了，列表和顶栏原地换成新标题，其余字段不变；
// 别的对话的标题事件也照改列表；空标题忽略；顶栏用 AnimatedSwitcher 淡入。
import 'package:assistant/core/api.dart';
import 'package:assistant/core/chat_socket.dart';
import 'package:assistant/features/chat/chat_controller.dart';
import 'package:assistant/models/resources.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'chat_controller_test.dart' show FakeSocket;

class _Api implements Api {
  String title = '帮我把 app 加一个深色模式';
  @override
  Future<dynamic> get(String path) async {
    if (path.startsWith('/api/conversations/')) return {'id': 'c1', 'messages': <dynamic>[]};
    if (path.startsWith('/api/conversations')) {
      return [
        {'id': 'c1', 'title': title, 'pinned': true, 'model': 'smart', 'updated_at': '2026-10-12T15:00:00Z'},
        {'id': 'c2', 'title': '别的', 'pinned': false, 'updated_at': '2026-10-12T14:00:00Z'},
      ];
    }
    return <dynamic>[];
  }

  @override
  dynamic noSuchMethod(Invocation i) => throw UnimplementedError();
}

Future<void> _settle() => Future<void>.delayed(const Duration(milliseconds: 10));

void main() {
  test('withTitle 只换标题', () {
    const c = ConversationSummary(id: 'a', title: 'x', pinned: true, model: 'smart', reasoning: 'high');
    final d = c.withTitle('y');
    expect([d.id, d.title, d.pinned, d.model, d.reasoning], ['a', 'y', true, 'smart', 'high']);
  });

  test('conversation.title：列表原地换字，再同步一次；空标题忽略', () async {
    final socket = FakeSocket();
    final api = _Api();
    final c = ProviderContainer(overrides: [chatSocketProvider.overrideWithValue(socket), apiProvider.overrideWithValue(api)]);
    c.listen(chatProvider(''), (_, _) {});
    addTearDown(c.dispose);
    await c.read(chatProvider('').notifier).refreshList();
    await _settle();
    expect(c.read(chatProvider('')).conversations.first.title, '帮我把 app 加一个深色模式');

    api.title = '给 App 加深色模式'; // 服务器那边已写好（随后的同步拉回同样的标题）
    socket.ctl.add({'type': 'conversation.title', 'conversation_id': 'c1', 'title': '给 App 加深色模式', 'turn_id': 't', 'seq': 9});
    await Future<void>.delayed(Duration.zero);
    var s = c.read(chatProvider(''));
    expect(s.conversations.first.title, '给 App 加深色模式'); // 同步刷新回来之前就已换好
    expect(s.conversations.first.pinned, true);
    expect(s.conversations.first.model, 'smart');
    expect(s.conversations[1].title, '别的');

    await _settle();
    socket.ctl.add({'type': 'conversation.title', 'conversation_id': 'c2', 'title': ''});
    await _settle();
    s = c.read(chatProvider(''));
    expect(s.conversations[1].title, '别的');
    expect(s.conversations.first.title, '给 App 加深色模式');
  });
}
