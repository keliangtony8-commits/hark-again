// 编辑最后一条用户消息：= 带 text 的 message.regenerate；本地先改气泡并撤掉回复，message.start 的 user_message 覆盖；
// 附件保留；被拒时以服务器为准；只有最后一条用户消息可编辑；界面：长按 → 编辑 → 输入框编辑态（草稿暂存、取消恢复）。
import 'package:assistant/core/api.dart';
import 'package:assistant/core/cache.dart';
import 'package:assistant/core/chat_socket.dart';
import 'package:assistant/features/chat/chat_controller.dart';
import 'package:assistant/features/chat/chat_view.dart';
import 'package:assistant/models/block.dart';
import 'package:assistant/features/chat/composer.dart';
import 'package:assistant/theme/app_theme.dart';
import 'package:flutter/material.dart';
import 'package:assistant/models/message.dart';
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
  test('编辑：发 regenerate+text，本地气泡换新文字、回复撤掉；id 不变', () async {
    final (c, socket, _) = _make();
    final ctl = c.read(chatProvider('').notifier);
    await ctl.open('c1');
    expect(c.read(chatProvider('')).editableId, 'u1');

    ctl.edit('  讲个冷笑话 ');
    var s = c.read(chatProvider(''));
    expect(socket.sent.single, {'type': 'message.regenerate', 'conversation_id': 'c1', 'message_id': 'a1', 'text': '讲个冷笑话'});
    expect(s.messages.map((m) => m.id), ['u1']);
    expect(plainText(s.messages.single.blocks), '讲个冷笑话');
    expect(s.editableId, isNull); // 生成中不能再改

    socket.ctl.add({
      'type': 'message.start', 'conversation_id': 'c1', 'user_message_id': 'u1', 'title': 't', 'replaced': ['a1'],
      'user_message': _msg('u1', 'user', '讲个冷笑话（服务器版）'),
    });
    socket.ctl.add({'type': 'message.done', 'message': _msg('a2', 'assistant', '冷笑话')});
    await _settle();
    s = c.read(chatProvider(''));
    expect(s.messages.map((m) => m.id), ['u1', 'a2']);
    expect(plainText(s.messages.first.blocks), '讲个冷笑话（服务器版）');
  });

  test('带附件的消息：附件保留，文字清空也能发；没附件时空文字不发', () async {
    final (c, socket, api) = _make();
    api.messages = [
      {
        'id': 'u1', 'role': 'user',
        'blocks': [
          {'type': 'text', 'text': '看图'},
          {'type': 'file', 'source': 'upload', 'id': 'f1', 'name': 'a.png', 'mime': 'image/png', 'size': 3},
        ],
      },
      _msg('a1', 'assistant', '是猫'),
    ];
    final ctl = c.read(chatProvider('').notifier);
    await ctl.open('c1');
    ctl.edit('');
    final m = c.read(chatProvider('')).messages.single;
    expect(m.blocks.single, isA<FileBlock>());
    expect(socket.sent.single['text'], '');

    final (c2, socket2, _) = _make();
    final ctl2 = c2.read(chatProvider('').notifier);
    await ctl2.open('c1');
    ctl2.edit('   ');
    expect(socket2.sent, isEmpty);
    expect(c2.read(chatProvider('')).messages.length, 2);
  });

  test('被拒（另一台设备接着聊了）→ 拉回服务器版本，原文字回来', () async {
    final (c, socket, api) = _make();
    final ctl = c.read(chatProvider('').notifier);
    await ctl.open('c1');
    ctl.edit('改过的');
    socket.ctl.add({'type': 'error', 'message': '这条回复已经不是最新的了，刷新后再试'});
    await _settle();
    final s = c.read(chatProvider(''));
    expect(s.messages.map((m) => plainText(m.blocks)), ['讲个笑话', '第一版']);
    expect(s.error, contains('不是最新'));
  });

  test('断线时不发、不改本地', () async {
    final (c, socket, _) = _make();
    final ctl = c.read(chatProvider('').notifier);
    await ctl.open('c1');
    socket.link(LinkStatus.down);
    await _settle();
    ctl.edit('新的');
    final s = c.read(chatProvider(''));
    expect(socket.sent, isEmpty);
    expect(plainText(s.messages.first.blocks), '讲个笑话');
    expect(s.error, contains('连接已断开'));
  });

  testWidgets('界面：只有最后一条用户消息长按有“编辑”；编辑态填原文、取消恢复草稿、发送走 edit', (tester) async {
    final socket = FakeSocket();
    final api = _Api()
      ..messages = [
        _msg('u1', 'user', '问题一'),
        _msg('a1', 'assistant', '回答一'),
        _msg('u2', 'user', '问题二'),
        _msg('a2', 'assistant', '回答二'),
      ];
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

    // 旧消息：只有复制
    await tester.longPress(find.text('问题一'));
    await tester.pumpAndSettle();
    expect(find.text('复制'), findsOneWidget);
    expect(find.text('编辑'), findsNothing);
    await tester.tapAt(const Offset(10, 10));
    await tester.pumpAndSettle();

    // 输入框里先有草稿
    await tester.enterText(find.byType(TextField), '草稿');
    await tester.longPress(find.text('问题二'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('编辑'));
    await tester.pumpAndSettle();
    expect(find.textContaining('编辑消息'), findsOneWidget);
    expect(tester.widget<TextField>(find.byType(TextField)).controller!.text, '问题二');

    await tester.tap(find.byTooltip('取消编辑'));
    await tester.pumpAndSettle();
    expect(find.textContaining('编辑消息'), findsNothing);
    expect(tester.widget<TextField>(find.byType(TextField)).controller!.text, '草稿');

    await tester.longPress(find.text('问题二'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('编辑'));
    await tester.pumpAndSettle();
    await tester.enterText(find.byType(TextField), '问题二（改）');
    await tester.pump();
    await tester.tap(find.bySemanticsLabel('保存并重新回答'));
    await tester.pumpAndSettle();
    expect(socket.sent.last, {'type': 'message.regenerate', 'conversation_id': 'c1', 'message_id': 'a2', 'text': '问题二（改）'});
    expect(find.text('回答二'), findsNothing);
    expect(find.text('问题二（改）'), findsOneWidget);
    expect(find.textContaining('编辑消息'), findsNothing);
    expect(tester.widget<TextField>(find.byType(TextField)).controller!.text, '草稿'); // 草稿回来
  });

  test('EditDraft.of 带出附件标记', () {
    expect(EditDraft.of(Message.fromJson(_msg('u', 'user', 'x'))).hasFiles, false);
  });
}
