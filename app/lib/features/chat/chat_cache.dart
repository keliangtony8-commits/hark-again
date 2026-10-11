// 对话的离线缓存（只被 chat_controller 用）：每个范围（主聊天 / 某项目）一份对话列表，
// 最近打开的 [keep] 个对话各一份消息。存的都是服务器原样 JSON。
// 最近使用顺序记在 msgs.index 里；超出就淘汰最久没打开的。写入串行，避免两个并发写把索引写乱。
// 例外：发件箱（本机还没进服务器的消息）不是服务器数据，按对话单独存在 outbox.<对话id>（新对话 outbox.new.<范围>），
//   用和服务器一样的块 JSON 形状写，读回时走 Block.fromJson；读回的一律算“发送失败”，由用户决定重发还是删除
//   （App 被杀或切走后它没机会发出，自动补发会让人意外，也可能挡住输入框）。
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/cache.dart';
import '../../models/block.dart';
import '../../models/message.dart';

class ChatCache {
  ChatCache(this._store, {this.keep = 30});
  final CacheStore _store;
  final int keep;
  Future<void> _tail = Future.value();

  static String _listKey(String projectId) => 'convs.${projectId.isEmpty ? 'main' : projectId}';
  static String _msgsKey(String id) => 'msgs.$id';
  static const _indexKey = 'msgs.index';
  static String _outboxKey(String projectId, String? id) =>
      id != null ? 'outbox.$id' : 'outbox.new.${projectId.isEmpty ? 'main' : projectId}';

  Future<T> _serial<T>(Future<T> Function() fn) {
    final next = _tail.then((_) => fn());
    _tail = next.then((_) {}, onError: (_) {});
    return next;
  }

  Future<List<Map<String, dynamic>>?> conversations(String projectId) async => _maps(await _store.read(_listKey(projectId)));

  Future<void> putConversations(String projectId, List<dynamic> raw) => _serial(() => _store.write(_listKey(projectId), raw));

  Future<List<Map<String, dynamic>>?> messages(String id) async => _maps(await _store.read(_msgsKey(id)));

  Future<void> putMessages(String id, List<dynamic> raw) => _serial(() async {
        await _store.write(_msgsKey(id), raw);
        final index = [id, for (final x in await _index()) if (x != id) x];
        for (final old in index.skip(keep)) {
          await _store.remove(_msgsKey(old));
        }
        await _store.write(_indexKey, index.take(keep).toList());
      });

  /// 某对话（[id] 为 null = 还没建的新对话）里本机未发出的消息，读回时都是 failed。
  /// 读也排进写队列：刚写的一定读得到（切走马上切回不丢）。
  Future<List<Message>> outbox(String projectId, String? id) => _serial(() async {
        final raw = _maps(await _store.read(_outboxKey(projectId, id))) ?? const [];
        return [
          for (final j in raw)
            if (j['id'] is String) Message(id: j['id'] as String, role: 'user', blocks: blocksFrom(j['blocks']), outbox: Outbox.failed),
        ];
      });

  /// 整份替换；空了就删掉文件。
  Future<void> putOutbox(String projectId, String? id, List<Message> unsent) => _serial(() async {
        final key = _outboxKey(projectId, id);
        if (unsent.isEmpty) return _store.remove(key);
        await _store.write(key, [
          for (final m in unsent) {'id': m.id, 'blocks': [for (final b in m.blocks) ?_blockJson(b)]},
        ]);
      });

  /// 用户消息只会有文字和附件两种块。
  static Map<String, dynamic>? _blockJson(Block b) => switch (b) {
        TextBlock() => {'type': 'text', 'text': b.text},
        FileBlock() => {
            'type': 'file',
            'source': b.source,
            'id': b.id,
            'name': b.name,
            'mime': b.mime,
            'size': b.size,
            if (b.projectId != null) 'project_id': b.projectId,
          },
        _ => null,
      };

  Future<void> forget(String id) => _serial(() async {
        await _store.remove(_msgsKey(id));
        await _store.remove(_outboxKey('', id));
        await _store.write(_indexKey, [for (final x in await _index()) if (x != id) x]);
      });

  Future<List<String>> _index() async => [for (final x in (await _store.read(_indexKey) as List?) ?? const []) '$x'];

  static List<Map<String, dynamic>>? _maps(Object? v) =>
      v is List ? [for (final x in v) if (x is Map) x.cast<String, dynamic>()] : null;
}

final chatCacheProvider = Provider<ChatCache>((ref) => ChatCache(ref.watch(cacheStoreProvider)));
