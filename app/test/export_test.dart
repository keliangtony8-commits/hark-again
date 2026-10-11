// 导出整段对话为 Markdown：格式（复用 copyText、跳过未发出/生成中、标已停止）、文件名清洗、
// 控制器取数（服务器优先，断网退回离线缓存，都没有/服务器拒绝 → 报错）。
import 'package:assistant/core/api.dart';
import 'package:assistant/core/cache.dart';
import 'package:assistant/core/chat_socket.dart';
import 'package:assistant/features/chat/chat_controller.dart';
import 'package:assistant/models/block.dart';
import 'package:assistant/models/export.dart';
import 'package:assistant/models/message.dart';
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
  List<dynamic>? messages;
  ApiError? fail;
  @override
  Future<dynamic> get(String path) async {
    if (!path.startsWith('/api/conversations/')) return <dynamic>[]; // 对话列表
    if (fail != null) throw fail!;
    return {'id': 'c1', 'messages': messages};
  }

  @override
  dynamic noSuchMethod(Invocation i) => throw UnimplementedError();
}

void main() {
  final at = DateTime(2026, 10, 11, 5, 7);

  test('格式：标题、导出时间、我/助手分段，代码块原样，已停止有标注', () {
    final md = conversationMarkdown('周末计划', [
      Message(id: 'u1', role: 'user', blocks: [const TextBlock('去哪玩？')]),
      Message(id: 'a1', role: 'assistant', blocks: [const TextBlock('去爬山'), const CodeBlock(language: 'sh', source: 'echo hi')]),
      Message(id: 'a2', role: 'assistant', blocks: [const TextBlock('半截')], stopped: true),
    ], at: at);
    expect(
        md,
        '# 周末计划\n\n> 导出于 2026-10-11 05:07 · 3 条消息\n\n## 我\n\n去哪玩？\n\n## 助手\n\n去爬山\n\n```sh\necho hi\n```'
        '\n\n## 助手\n\n半截\n\n*（已停止）*\n');
  });

  test('跳过本机未发出、正在生成、没有可导出内容的消息', () {
    final md = conversationMarkdown('  ', [
      Message(id: 'u1', role: 'user', blocks: [const TextBlock('发出去了')]),
      Message(id: 'u2', role: 'user', blocks: [const TextBlock('没发出')], outbox: Outbox.failed),
      Message(id: 'a1', role: 'assistant', blocks: [const TextBlock('写到一半')], pending: true),
      const Message(id: 'a2', role: 'assistant', blocks: []),
    ], at: at);
    expect(md, '# 新对话\n\n> 导出于 2026-10-11 05:07 · 1 条消息\n\n## 我\n\n发出去了\n');
  });

  test('文件名：非法字符换下划线，空标题有默认名，过长截断', () {
    expect(exportFileName('a/b: c?'), 'a_b_ c_.md');
    expect(exportFileName('  '), '对话.md');
    expect(exportFileName('长' * 100), '${'长' * 60}.md');
  });

  group('ChatController.exportMarkdown', () {
    late _Api api;
    late MemoryCacheStore store;
    late ProviderContainer c;
    setUp(() {
      api = _Api();
      store = MemoryCacheStore();
      c = ProviderContainer(overrides: [
        chatSocketProvider.overrideWithValue(FakeSocket()),
        apiProvider.overrideWithValue(api),
        cacheStoreProvider.overrideWithValue(store),
      ]);
      addTearDown(c.dispose);
      c.listen(chatProvider(''), (_, _) {}); // 保持控制器存活（同页面在用时）
    });

    test('以服务器为准，并顺手写进缓存；之后断网仍能从缓存导出', () async {
      api.messages = [_msg('u1', 'user', '你好'), _msg('a1', 'assistant', '在呢', status: 'stopped')];
      final ctl = c.read(chatProvider('').notifier);
      final md = await ctl.exportMarkdown('c1', '问候');
      expect(md, contains('## 我\n\n你好'));
      expect(md, contains('在呢\n\n*（已停止）*'));
      await Future<void>.delayed(Duration.zero);

      api.fail = ApiError('断网');
      expect(await ctl.exportMarkdown('c1', '问候'), contains('在呢'));
    });

    test('断网又没有缓存 → 报错；服务器拒绝 → 原样报错，不退回缓存', () async {
      final ctl = c.read(chatProvider('').notifier);
      api.fail = ApiError('断网');
      await expectLater(ctl.exportMarkdown('c9', 'x'), throwsA(isA<ApiError>().having((e) => e.message, 'message', contains('离线副本'))));
      api.fail = ApiError('对话不存在', 404);
      await expectLater(ctl.exportMarkdown('c9', 'x'), throwsA(isA<ApiError>().having((e) => e.status, 'status', 404)));
    });
  });
}
