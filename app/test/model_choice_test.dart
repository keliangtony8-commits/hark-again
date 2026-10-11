// 每个对话选模型：目录解析（默认回落）、打开对话取模型（列表 → 服务器详情）、
// 已有对话 PATCH、断网时随下一条消息带上、新对话随第一条消息带上、换模型重答；输入框模型钮点一下切换。
import 'package:assistant/core/api.dart';
import 'package:assistant/core/cache.dart';
import 'package:assistant/core/chat_socket.dart';
import 'package:assistant/features/chat/chat_controller.dart';
import 'package:assistant/features/chat/chat_view.dart';
import 'package:assistant/models/resources.dart';
import 'package:assistant/theme/app_theme.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'chat_controller_test.dart' show FakeSocket;

const _catalog = {
  'default': 'fast',
  'models': [
    {'id': 'fast', 'label': '快速'},
    {'id': 'smart', 'label': '深度'},
  ],
};

class _Api implements Api {
  String? listModel = 'smart'; // 列表里 c1 的模型
  String? detailModel = 'smart'; // 详情里 c1 的模型
  bool offline = false;
  final patches = <Map<String, dynamic>>[];

  @override
  Future<dynamic> get(String path) async {
    if (offline) throw ApiError('断网');
    if (path == '/api/catalog/models') return _catalog;
    if (path.startsWith('/api/conversations/')) {
      return {
        'id': 'c1',
        'model': detailModel,
        'messages': [
          {'id': 'u1', 'role': 'user', 'blocks': [{'type': 'text', 'text': '嗨'}]},
          {'id': 'a1', 'role': 'assistant', 'blocks': [{'type': 'text', 'text': '你好'}]},
        ],
      };
    }
    if (path.startsWith('/api/conversations')) {
      return [
        {'id': 'c1', 'title': '旧对话', 'model': listModel, 'updated_at': '2026-10-11T00:00:00+08:00'},
      ];
    }
    return null;
  }

  @override
  Future<dynamic> patch(String path, Object body) async {
    if (offline) throw ApiError('断网');
    patches.add({'path': path, ...(body as Map<String, dynamic>)});
    return {'id': 'c1'};
  }

  @override
  dynamic noSuchMethod(Invocation i) => throw UnimplementedError();
}

(ProviderContainer, FakeSocket, _Api) _make() {
  final socket = FakeSocket();
  final api = _Api();
  final c = ProviderContainer(overrides: [
    chatSocketProvider.overrideWithValue(socket),
    apiProvider.overrideWithValue(api),
    cacheStoreProvider.overrideWithValue(MemoryCacheStore()),
  ]);
  addTearDown(c.dispose);
  c.listen(chatProvider(''), (_, _) {});
  return (c, socket, api);
}

Future<void> _settle() async {
  for (var i = 0; i < 8; i++) {
    await Future<void>.delayed(Duration.zero);
  }
}

void main() {
  test('ModelCatalog：选择 → 生效项，删掉的别名回落默认；选默认存 null', () {
    final cat = ModelCatalog.fromJson(_catalog);
    expect(cat.selectable, isTrue);
    expect(cat.effective(null)!.label, '快速');
    expect(cat.effective('smart')!.label, '深度');
    expect(cat.effective('gone')!.id, 'fast');
    expect(cat.toChoice('fast'), isNull);
    expect(cat.toChoice('smart'), 'smart');
    expect(ModelCatalog.fromJson({'default': 'fast', 'models': [{'id': 'fast', 'label': '快速'}]}).selectable, isFalse);
  });

  test('打开对话：先用列表里的模型，再以服务器详情为准', () async {
    final (c, _, api) = _make();
    final ctl = c.read(chatProvider('').notifier);
    await _settle();
    api.offline = true; // 拿不到详情：用列表里的
    await ctl.open('c1');
    expect(c.read(chatProvider('')).model, 'smart');
    api.offline = false;
    api.detailModel = null; // 另一台设备刚改回默认：详情为准
    await ctl.open('c1');
    expect(c.read(chatProvider('')).model, isNull);
    await ctl.open(null);
    expect(c.read(chatProvider('')).model, isNull); // 新对话 = 默认
  });

  test('已有对话：setModel 立刻 PATCH，之后的消息不再带 model', () async {
    final (c, socket, api) = _make();
    final ctl = c.read(chatProvider('').notifier);
    await _settle();
    await ctl.open('c1');
    await ctl.setModel(null);
    expect(api.patches.single, {'path': '/api/conversations/c1', 'model': ''});
    expect(c.read(chatProvider('')).model, isNull);
    ctl.send('下一题');
    expect(socket.sent.last.containsKey('model'), isFalse);
  });

  test('断网改了模型：随下一条消息带上，只带一次', () async {
    final (c, socket, api) = _make();
    final ctl = c.read(chatProvider('').notifier);
    await _settle();
    await ctl.open('c1');
    api.offline = true;
    await ctl.setModel(null);
    expect(c.read(chatProvider('')).error, isNull); // 断网不报错，等消息带过去
    api.offline = false;
    ctl.send('简单问题');
    expect(socket.sent.last['model'], '');
    socket.ctl.add({'type': 'message.start', 'conversation_id': 'c1', 'user_message_id': 'u2', 'title': '旧对话'});
    socket.ctl.add({'type': 'message.done', 'message': {'id': 'a2', 'role': 'assistant', 'blocks': [{'type': 'text', 'text': '好'}]}});
    await _settle();
    ctl.send('再问');
    expect(socket.sent.last.containsKey('model'), isFalse);
  });

  test('新对话：先选深度，第一条消息带上；换模型重答 = 切换后点重新生成', () async {
    final (c, socket, _) = _make();
    final ctl = c.read(chatProvider('').notifier);
    await _settle();
    await ctl.setModel('smart');
    ctl.send('难题');
    expect(socket.sent.last['model'], 'smart');
    expect(socket.sent.last['conversation_id'], isNull);
    socket.ctl.add({'type': 'message.start', 'conversation_id': 'c9', 'user_message_id': 'u1', 'title': '难题'});
    socket.ctl.add({'type': 'message.done', 'message': {'id': 'a1', 'role': 'assistant', 'blocks': [{'type': 'text', 'text': '答'}]}});
    await _settle();
    expect(c.read(chatProvider('')).model, 'smart');

    final (c2, socket2, api2) = _make();
    final ctl2 = c2.read(chatProvider('').notifier);
    await _settle();
    await ctl2.open('c1');
    api2.offline = true; // PATCH 失败 → 由重新生成带过去
    await ctl2.setModel(null);
    api2.offline = false;
    ctl2.regenerate();
    expect(socket2.sent.last, {'type': 'message.regenerate', 'conversation_id': 'c1', 'message_id': 'a1', 'model': ''});
  });

  testWidgets('输入框模型钮：显示当前模型，点一下切换并 PATCH', (tester) async {
    final socket = FakeSocket();
    final api = _Api();
    late WidgetRef ref;
    await tester.pumpWidget(ProviderScope(
      overrides: [
        chatSocketProvider.overrideWithValue(socket),
        apiProvider.overrideWithValue(api),
        cacheStoreProvider.overrideWithValue(MemoryCacheStore()),
      ],
      child: MaterialApp(
        theme: buildTheme(Brightness.light),
        home: Scaffold(body: Consumer(builder: (_, r, _) {
          ref = r;
          return const ChatView();
        })),
      ),
    ));
    await tester.pumpAndSettle();
    await ref.read(chatProvider('').notifier).open('c1');
    await tester.pumpAndSettle();
    expect(find.text('深度'), findsOneWidget);
    await tester.tap(find.bySemanticsLabel(RegExp('模型：深度')));
    await tester.pumpAndSettle();
    expect(find.text('快速'), findsOneWidget);
    expect(find.text('深度'), findsNothing);
    expect(api.patches.single['model'], '');
  });
}
