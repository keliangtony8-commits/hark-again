// 消息操作：复制（Markdown，表格/代码保留格式）、重新生成最后一条回复、上一轮失败时重试；
// 服务器拒绝时以服务器为准拉回旧回复；断线不排队；界面只在最后一条回复上给“重新生成”。
import 'package:assistant/core/api.dart';
import 'package:assistant/core/cache.dart';
import 'package:assistant/core/chat_socket.dart';
import 'package:assistant/features/chat/chat_controller.dart';
import 'package:assistant/features/chat/chat_view.dart';
import 'package:assistant/models/block.dart';
import 'package:assistant/theme/app_theme.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'chat_controller_test.dart' show FakeSocket;

Map<String, dynamic> _msg(String id, String role, String text) => {
      'id': id,
      'role': role,
      'blocks': [
        {'type': 'text', 'text': text}
      ],
    };

class _Api implements Api {
  List<dynamic> messages = [];
  int fetches = 0;
  @override
  Future<dynamic> get(String path) async {
    if (path.startsWith('/api/conversations/')) {
      fetches++;
      return {'id': 'c1', 'messages': messages};
    }
    if (path.startsWith('/api/conversations')) return <dynamic>[];
    return null;
  }

  @override
  dynamic noSuchMethod(Invocation i) => throw UnimplementedError();
}

(ProviderContainer, FakeSocket, _Api) _make() {
  final socket = FakeSocket();
  final api = _Api()
    ..messages = [_msg('u1', 'user', '讲个笑话'), _msg('a1', 'assistant', '第一版')];
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
  test('copyText：文字、代码、表格转 Markdown，过程卡片不复制', () {
    final text = copyText(blocksFrom([
      {'type': 'text', 'text': '结论如下 '},
      {'type': 'approval', 'id': 'x', 'title': '运行命令', 'detail': 'ls', 'state': 'approved'},
      {'type': 'code', 'language': 'py', 'source': 'print(1)'},
      {
        'type': 'table',
        'columns': ['名', '价'],
        'rows': [
          ['A', '1'],
        ]
      },
    ]));
    expect(text, '结论如下\n\n```py\nprint(1)\n```\n\n| 名 | 价 |\n| --- | --- |\n| A | 1 |');
  });

  test('重新生成：本地先撤旧回复 → 新回复接上；同一条用户消息不重复', () async {
    final (c, socket, _) = _make();
    final ctl = c.read(chatProvider('').notifier);
    await ctl.open('c1');
    expect(c.read(chatProvider('')).canRegenerate, true);

    ctl.regenerate();
    var s = c.read(chatProvider(''));
    expect(socket.sent.single, {'type': 'message.regenerate', 'conversation_id': 'c1', 'message_id': 'a1'});
    expect(s.streaming, true);
    expect(s.messages.map((m) => m.id), ['u1']);
    expect(s.canRegenerate, false);

    socket.ctl.add({'type': 'message.start', 'conversation_id': 'c1', 'user_message_id': 'u1', 'title': 't', 'replaced': ['a1']});
    socket.ctl.add({'type': 'block.start', 'index': 0, 'block': {'type': 'text', 'text': '第二版'}});
    socket.ctl.add({'type': 'message.done', 'message': _msg('a2', 'assistant', '第二版')});
    await _settle();
    s = c.read(chatProvider(''));
    expect(s.messages.map((m) => m.id), ['u1', 'a2']);
    expect(s.streaming, false);
    expect(s.canRegenerate, true);
  });

  test('服务器拒绝（不是最新的了）→ 重新拉对话，旧回复回来', () async {
    final (c, socket, api) = _make();
    final ctl = c.read(chatProvider('').notifier);
    await ctl.open('c1');
    ctl.regenerate();
    api.messages = [...api.messages, _msg('u2', 'user', '另一台设备'), _msg('a3', 'assistant', '新的')];
    socket.ctl.add({'type': 'error', 'message': '这条回复已经不是最新的了，刷新后再试'});
    await _settle();
    final s = c.read(chatProvider(''));
    expect(s.messages.map((m) => m.id), ['u1', 'a1', 'u2', 'a3']);
    expect(s.error, contains('不是最新'));
  });

  test('上一轮失败：最后一条是用户消息 → 重试不带 message_id；断线时不排队只提示', () async {
    final (c, socket, api) = _make();
    api.messages = [_msg('u1', 'user', '讲个笑话')];
    final ctl = c.read(chatProvider('').notifier);
    await ctl.open('c1');
    socket.link(LinkStatus.down);
    await _settle();
    ctl.regenerate();
    expect(socket.sent, isEmpty);
    expect(c.read(chatProvider('')).error, contains('连接已断开'));
    expect(c.read(chatProvider('')).streaming, false);

    socket.link(LinkStatus.open);
    await _settle();
    ctl.regenerate();
    expect(socket.sent.single, {'type': 'message.regenerate', 'conversation_id': 'c1'});
  });

  test('重新生成还没开始就断线：不把用户消息标失败，连上后从服务器补全', () async {
    final (c, socket, api) = _make();
    final ctl = c.read(chatProvider('').notifier);
    await ctl.open('c1');
    final before = api.fetches;
    ctl.regenerate();
    socket.link(LinkStatus.down);
    await _settle();
    var s = c.read(chatProvider(''));
    expect(s.streaming, false);
    expect(s.messages.every((m) => !m.unsent), true);
    socket.link(LinkStatus.open);
    await _settle();
    s = c.read(chatProvider(''));
    expect(api.fetches, greaterThan(before));
    expect(s.messages.map((m) => m.id), ['u1', 'a1']);
  });

  testWidgets('界面：每条回复可复制，只有最后一条有“重新生成”；失败时错误条上有“重试”', (tester) async {
    final socket = FakeSocket();
    final api = _Api()
      ..messages = [
        _msg('u1', 'user', '问题一'),
        _msg('a1', 'assistant', '回答一'),
        _msg('u2', 'user', '问题二'),
        _msg('a2', 'assistant', '回答二'),
      ];
    String? copied;
    tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(SystemChannels.platform, (call) async {
      if (call.method == 'Clipboard.setData') copied = (call.arguments as Map)['text'] as String;
      return null;
    });
    final container = ProviderContainer(overrides: [
      chatSocketProvider.overrideWithValue(socket),
      apiProvider.overrideWithValue(api),
      cacheStoreProvider.overrideWithValue(MemoryCacheStore()),
    ]);
    addTearDown(container.dispose);
    await tester.pumpWidget(UncontrolledProviderScope(
      container: container,
      child: MaterialApp(theme: buildTheme(Brightness.light), home: const Scaffold(body: ChatView())),
    ));
    await container.read(chatProvider('').notifier).open('c1');
    await tester.pumpAndSettle();

    // §I：气泡下没有常驻图标；长按回复出动作菜单，只有最后一条有“重新生成”
    expect(find.byTooltip('复制'), findsNothing);
    await tester.longPress(find.text('回答一'));
    await tester.pumpAndSettle();
    expect(find.text('重新生成'), findsNothing);
    await tester.tapAt(const Offset(10, 10)); // 关掉菜单
    await tester.pumpAndSettle();

    await tester.longPress(find.text('回答二'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('复制'));
    await tester.pumpAndSettle();
    expect(copied, '回答二');
    expect(find.text('已复制'), findsOneWidget);
    await tester.pump(const Duration(seconds: 4));
    await tester.pumpAndSettle();

    await tester.longPress(find.text('回答二'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('重新生成'));
    await tester.pumpAndSettle();
    expect(socket.sent.last['message_id'], 'a2');
    expect(find.text('回答二'), findsNothing);

    socket.ctl.add({'type': 'message.start', 'conversation_id': 'c1', 'user_message_id': 'u2', 'title': 't', 'replaced': ['a2']});
    socket.ctl.add({'type': 'error', 'message': '模型调用失败：超时'});
    api.messages = api.messages.sublist(0, 3);
    await tester.pumpAndSettle();
    expect(find.text('重试'), findsOneWidget);
    await tester.tap(find.text('重试'));
    await tester.pumpAndSettle();
    expect(socket.sent.last, {'type': 'message.regenerate', 'conversation_id': 'c1'});
  });
}
