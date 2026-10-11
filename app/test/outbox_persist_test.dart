// 发件箱持久化：未发出的消息切走对话、App 被杀（容器重建）后再打开，以“发送失败”回来；
// 发出后从发件箱消失；删除对话连同发件箱一起清掉。
import 'package:assistant/core/api.dart';
import 'package:assistant/core/cache.dart';
import 'package:assistant/core/chat_socket.dart';
import 'package:assistant/features/chat/chat_controller.dart';
import 'package:assistant/models/block.dart';
import 'package:assistant/models/message.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'chat_controller_test.dart' show FakeSocket;

class _Api implements Api {
  @override
  Future<dynamic> get(String path) async {
    if (path.startsWith('/api/conversations/')) {
      final id = path.split('/').last;
      return {'id': id, 'messages': [{'id': 'srv-$id', 'role': 'assistant', 'blocks': [{'type': 'text', 'text': '旧'}]}]};
    }
    if (path.startsWith('/api/conversations')) return <dynamic>[];
    return null;
  }

  @override
  Future<dynamic> delete(String path) async => null;

  @override
  dynamic noSuchMethod(Invocation i) => throw UnimplementedError();
}

/// 同一个磁盘（store）上新建一个容器 = App 重启。
(ProviderContainer, FakeSocket) _boot(MemoryCacheStore store, {LinkStatus link = LinkStatus.down}) {
  final socket = FakeSocket(initial: link);
  final c = ProviderContainer(overrides: [
    chatSocketProvider.overrideWithValue(socket),
    apiProvider.overrideWithValue(_Api()),
    cacheStoreProvider.overrideWithValue(store),
  ]);
  addTearDown(c.dispose);
  return (c, socket);
}

Future<void> _settle() async {
  for (var i = 0; i < 8; i++) {
    await Future<void>.delayed(Duration.zero);
  }
}

void main() {
  const file = FileBlock(source: 'upload', id: 'f1', name: 'a.png', mime: 'image/png', size: 12);

  test('切走再切回：未发出的消息带着附件回来，状态为发送失败', () async {
    final store = MemoryCacheStore();
    final (c, _) = _boot(store);
    final ctl = c.read(chatProvider('').notifier);
    await ctl.open('c1');
    ctl.send('没发出去', files: [file]);
    await _settle();
    await ctl.open('c2');
    expect(c.read(chatProvider('')).messages.any((m) => m.unsent), false);
    await ctl.open('c1');
    final ms = c.read(chatProvider('')).messages;
    expect(ms.map((m) => m.id).first, 'srv-c1');
    final back = ms.last;
    expect(back.outbox, Outbox.failed);
    expect(plainText(back.blocks), '没发出去');
    final f = back.blocks.whereType<FileBlock>().single;
    expect((f.id, f.name, f.mime, f.size), ('f1', 'a.png', 'image/png', 12));
  });

  test('App 被杀后重开：新对话里的草稿消息也回来，可重发；发出后发件箱清空', () async {
    final store = MemoryCacheStore();
    {
      final (c, _) = _boot(store);
      final ctl = c.read(chatProvider('p1').notifier);
      await _settle();
      ctl.send('新对话第一句');
      await _settle();
      c.dispose();
    }
    final (c, socket) = _boot(store);
    final ctl = c.read(chatProvider('p1').notifier);
    await _settle();
    var m = c.read(chatProvider('p1')).messages.single;
    expect(m.outbox, Outbox.failed);
    expect(c.read(chatProvider('p1')).busy, false);
    expect(c.read(chatProvider('')).messages, isEmpty); // 各范围的发件箱互不串

    ctl.resend(m.id);
    socket.link(LinkStatus.open);
    await _settle();
    expect(socket.sent.single['text'], '新对话第一句');
    expect(socket.sent.single['project_id'], 'p1');
    m = c.read(chatProvider('p1')).messages.single;
    expect(m.outbox, Outbox.sent);
    expect(store.data.keys.where((k) => k.startsWith('outbox.')), isEmpty);
  });

  test('删除失败消息、删除对话都会清掉发件箱', () async {
    final store = MemoryCacheStore();
    final (c, _) = _boot(store);
    final ctl = c.read(chatProvider('').notifier);
    await ctl.open('c1');
    ctl.send('x');
    await _settle();
    expect(store.data.containsKey('outbox.c1'), true);
    ctl.discard(c.read(chatProvider('')).messages.last.id);
    await _settle();
    expect(store.data.containsKey('outbox.c1'), false);

    ctl.send('y');
    await _settle();
    await ctl.remove('c1');
    await _settle();
    expect(store.data.containsKey('outbox.c1'), false);
  });
}
