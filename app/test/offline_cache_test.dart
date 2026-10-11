// 离线缓存：瞬开、断网可读、重试恢复、LRU 淘汰、退出登录清空、文件落盘。
import 'dart:io';

import 'package:assistant/core/api.dart';
import 'package:assistant/core/cache.dart';
import 'package:assistant/core/chat_socket.dart';
import 'package:assistant/core/resource.dart';
import 'package:assistant/features/chat/chat_cache.dart';
import 'package:assistant/features/chat/chat_controller.dart';
import 'package:assistant/features/chat/chat_view.dart';
import 'package:assistant/models/block.dart';
import 'package:assistant/theme/app_theme.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'chat_controller_test.dart' show FakeSocket;

/// 可以“拔网线”的假服务器。
class SwitchApi implements Api {
  bool online = true;
  final gets = <String>[];
  List<dynamic> conversations = [
    {'id': 'c1', 'title': '旅行计划', 'updated_at': '2026-10-11T00:00:00Z'}
  ];
  Map<String, List<dynamic>> messages = {
    'c1': [
      {'id': 'm1', 'role': 'user', 'blocks': [{'type': 'text', 'text': '去哪玩'}]},
      {'id': 'm2', 'role': 'assistant', 'blocks': [{'type': 'text', 'text': '去杭州'}]},
    ]
  };
  List<dynamic> projects = [
    {'id': 'p1', 'name': '毕设', 'emoji': '🎓', 'rules': ''}
  ];

  @override
  Future<dynamic> get(String path) async {
    gets.add(path);
    if (!online) throw ApiError('连不上服务器');
    if (path.startsWith('/api/conversations/')) return {'id': path.split('/').last, 'messages': messages[path.split('/').last]};
    if (path.startsWith('/api/conversations')) return conversations;
    if (path == '/api/projects') return projects;
    return null;
  }

  @override
  dynamic noSuchMethod(Invocation i) => throw UnimplementedError();
}

Future<void> settle() async {
  for (var i = 0; i < 5; i++) {
    await Future<void>.delayed(Duration.zero);
  }
}

ProviderContainer make(SwitchApi api, CacheStore store) {
  final c = ProviderContainer(overrides: [
    chatSocketProvider.overrideWithValue(FakeSocket()),
    apiProvider.overrideWithValue(api),
    cacheStoreProvider.overrideWithValue(store),
  ]);
  addTearDown(c.dispose);
  return c;
}

String textOf(ChatState s, int i) => (s.messages[i].blocks.single as TextBlock).text;

void main() {
  test('在线打开会写缓存；断网后重开：列表和消息都来自缓存，并标记离线', () async {
    final api = SwitchApi();
    final store = MemoryCacheStore();
    var c = make(api, store);
    c.read(chatProvider(''));
    await settle();
    await c.read(chatProvider('').notifier).open('c1');
    await settle();
    expect(store.data.keys, containsAll(['convs.main', 'msgs.c1', 'msgs.index']));

    // 第二次启动：没网
    api.online = false;
    c.dispose();
    c = make(api, store);
    c.read(chatProvider(''));
    await settle();
    var s = c.read(chatProvider(''));
    expect(s.conversations.single.title, '旅行计划');
    expect(s.offline, true);

    await c.read(chatProvider('').notifier).open('c1');
    s = c.read(chatProvider(''));
    expect(s.messages.length, 2);
    expect(textOf(s, 1), '去杭州');
    expect(s.offline, true);
    expect(s.error, isNull); // 有缓存就不报错

    // 恢复网络 + 服务器有新消息 → 重试后同步
    api.online = true;
    api.messages['c1'] = [
      ...api.messages['c1']!,
      {'id': 'm3', 'role': 'assistant', 'blocks': [{'type': 'text', 'text': '再加一天'}]},
    ];
    await c.read(chatProvider('').notifier).sync();
    s = c.read(chatProvider(''));
    expect(s.offline, false);
    expect(s.messages.length, 3);
  });

  test('没缓存又断网：显示错误而不是空白', () async {
    final api = SwitchApi()..online = false;
    final c = make(api, MemoryCacheStore());
    c.read(chatProvider(''));
    await settle();
    await c.read(chatProvider('').notifier).open('c1');
    final s = c.read(chatProvider(''));
    expect(s.messages, isEmpty);
    expect(s.error, '连不上服务器');
  });

  test('快速切换对话：慢的旧请求不会盖掉新对话', () async {
    final api = SwitchApi();
    api.messages['c2'] = [
      {'id': 'x', 'role': 'user', 'blocks': [{'type': 'text', 'text': '第二个'}]}
    ];
    final c = make(api, MemoryCacheStore());
    final ctl = c.read(chatProvider('').notifier);
    final first = ctl.open('c1');
    final second = ctl.open('c2');
    await Future.wait([first, second]);
    final s = c.read(chatProvider(''));
    expect(s.activeId, 'c2');
    expect(textOf(s, 0), '第二个');
  });

  test('ChatCache 只留最近 keep 个对话，删除对话会清掉它', () async {
    final store = MemoryCacheStore();
    final cache = ChatCache(store, keep: 2);
    await Future.wait([cache.putMessages('a', []), cache.putMessages('b', []), cache.putMessages('c', [])]);
    expect(await cache.messages('a'), isNull);
    expect(await cache.messages('c'), isNotNull);
    expect(await store.read('msgs.index'), ['c', 'b']);
    await cache.putMessages('b', [
      {'id': '1'}
    ]); // 重新打开 b → 排到最前
    expect(await store.read('msgs.index'), ['b', 'c']);
    await cache.forget('c');
    expect(await cache.messages('c'), isNull);
    expect(await store.read('msgs.index'), ['b']);
  });

  test('带 cacheKey 的资源：离线时用缓存，在线时后台刷新并回写', () async {
    final api = SwitchApi();
    final store = MemoryCacheStore();
    var c = make(api, store);
    expect((await c.read(projectsProvider.future)).single.name, '毕设');
    await settle();
    expect(await store.read('projects'), isNotNull);

    api.online = false;
    c.dispose();
    c = make(api, store);
    expect((await c.read(projectsProvider.future)).single.name, '毕设');
    await settle();
    expect(c.read(projectsProvider).hasError, false); // 后台刷新失败不打扰

    api.online = true;
    api.projects = [
      {'id': 'p1', 'name': '毕设（改）', 'emoji': '🎓', 'rules': ''}
    ];
    c.dispose();
    c = make(api, store);
    expect((await c.read(projectsProvider.future)).single.name, '毕设'); // 先给缓存
    await settle();
    expect(c.read(projectsProvider).value!.single.name, '毕设（改）'); // 再换成新的
    expect((await store.read('projects') as List).single['name'], '毕设（改）');
  });

  test('FileCacheStore：原子写、读回、按服务器分目录、clear 全清', () async {
    final tmp = await Directory.systemTemp.createTemp('cache_test');
    addTearDown(() => tmp.delete(recursive: true));
    final a = FileCacheStore(cacheNamespace('https://a.example'), root: () async => tmp);
    final b = FileCacheStore(cacheNamespace('https://b.example'), root: () async => tmp);
    expect(cacheNamespace('https://a.example'), isNot(cacheNamespace('https://b.example')));
    await a.write('msgs/../x', {'k': '中文'});
    expect(await a.read('msgs/../x'), {'k': '中文'});
    expect(await b.read('msgs/../x'), isNull);
    await a.clear();
    expect(await a.read('msgs/../x'), isNull);
    expect(await File('${tmp.path}/cache').exists(), false);
    await a.write('k', 1); // clear 之后还能继续用
    expect(await a.read('k'), 1);
  });

  testWidgets('离线时聊天区顶部出现离线条，重试成功后收起', (tester) async {
    final api = SwitchApi()..online = false;
    final store = MemoryCacheStore();
    await ChatCache(store).putConversations('', api.conversations);
    await tester.pumpWidget(ProviderScope(
      overrides: [
        chatSocketProvider.overrideWithValue(FakeSocket()),
        apiProvider.overrideWithValue(api),
        cacheStoreProvider.overrideWithValue(store),
      ],
      child: MaterialApp(theme: buildTheme(Brightness.light), home: const Scaffold(body: ChatView())),
    ));
    await tester.pumpAndSettle();
    expect(find.byType(OfflineBar), findsOneWidget);
    expect(find.text('离线 · 显示的是上次同步的内容'), findsOneWidget);

    api.online = true;
    await tester.tap(find.text('重试'));
    await tester.pumpAndSettle();
    expect(find.byType(OfflineBar), findsNothing);
  });
}
