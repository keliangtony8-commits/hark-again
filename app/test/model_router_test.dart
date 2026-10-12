// 自动选模型（v1.70，后端 model_router）：目录里的“自动”项（auto + routes）解析、钮上“自动 · 快速”、菜单说明；
// 打开对话取 routed_model、turn.model 事件换字；旧服务器没有自动项。
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
    {'id': 'auto', 'label': '自动', 'auto': true, 'routes': {'simple': 'fast', 'complex': 'smart'}},
    {'id': 'fast', 'label': '快速'},
    {'id': 'smart', 'label': '深度'},
  ],
};

class _Api implements Api {
  String? routed = 'fast';

  @override
  Future<dynamic> get(String path) async {
    if (path == '/api/catalog/models') return _catalog;
    if (path.startsWith('/api/conversations/')) {
      return {
        'id': 'c1',
        'model': 'auto',
        'routed_model': routed,
        'messages': [
          {'id': 'u1', 'role': 'user', 'blocks': [{'type': 'text', 'text': '嗨'}]},
          {'id': 'a1', 'role': 'assistant', 'blocks': [{'type': 'text', 'text': '你好'}]},
        ],
      };
    }
    if (path.startsWith('/api/conversations')) {
      return [
        {'id': 'c1', 'title': '旧对话', 'model': 'auto', 'routed_model': 'smart', 'updated_at': '2026-10-11T00:00:00+08:00'},
      ];
    }
    return null;
  }

  @override
  Future<dynamic> patch(String path, Object body) async => {'id': 'c1'};

  @override
  dynamic noSuchMethod(Invocation i) => throw UnimplementedError();
}

Future<void> _settle() async {
  for (var i = 0; i < 8; i++) {
    await Future<void>.delayed(Duration.zero);
  }
}

void main() {
  test('目录：自动项、两档、钮上的字、菜单说明；旧服务器没有自动', () {
    final cat = ModelCatalog.fromJson(_catalog);
    expect(cat.autoId, 'auto');
    expect(cat.routes, {'simple': 'fast', 'complex': 'smart'});
    expect(cat.isAuto('auto'), isTrue);
    expect(cat.isAuto('fast'), isFalse);
    final auto = cat.effective('auto')!;
    expect(cat.chipLabel(auto, 'fast'), '自动 · 快速');
    expect(cat.chipLabel(auto, null), '自动');
    expect(cat.chipLabel(cat.effective('smart')!, 'fast'), '深度'); // 手选的模型：不显示路由
    expect(cat.chipLabel(auto, 'gone'), '自动 · gone');
    expect(cat.autoHint(), '简单的事用快速，复杂的用深度，每轮自动挑');
    final old = ModelCatalog.fromJson({'default': 'fast', 'models': [{'id': 'fast', 'label': '快速'}, {'id': 'smart', 'label': '深度'}]});
    expect(old.autoId, isNull);
    expect(old.isAuto('auto'), isFalse);
    expect(old.autoHint(), isNull);
  });

  test('打开对话：列表里的 routed_model，再以详情为准；turn.model 换掉；新对话清空', () async {
    final socket = FakeSocket();
    final api = _Api();
    final c = ProviderContainer(overrides: [
      chatSocketProvider.overrideWithValue(socket),
      apiProvider.overrideWithValue(api),
      cacheStoreProvider.overrideWithValue(MemoryCacheStore()),
    ]);
    addTearDown(c.dispose);
    c.listen(chatProvider(''), (_, _) {});
    final ctl = c.read(chatProvider('').notifier);
    await _settle();
    await ctl.open('c1');
    expect(c.read(chatProvider('')).routed, 'fast');
    ctl.send('帮我查原因');
    socket.ctl.add({'type': 'message.start', 'conversation_id': 'c1', 'user_message_id': 'u2', 'title': '旧对话'});
    socket.ctl.add({'type': 'turn.model', 'model': 'smart', 'label': '深度', 'complexity': 'complex', 'source': 'router/classifier', 'reason': '要排查'});
    await _settle();
    expect(c.read(chatProvider('')).routed, 'smart');
    socket.ctl.add({'type': 'message.done', 'message': {'id': 'a2', 'role': 'assistant', 'blocks': [{'type': 'text', 'text': '好'}]}});
    await _settle();
    expect(c.read(chatProvider('')).routed, 'smart');
    await ctl.open(null);
    expect(c.read(chatProvider('')).routed, isNull);
  });

  testWidgets('输入框模型钮：自动 · 快速，这一轮路由到深度后换字', (tester) async {
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
    expect(find.text('自动 · 快速'), findsOneWidget);
    expect(find.byIcon(Icons.alt_route_rounded), findsOneWidget);
    ref.read(chatProvider('').notifier).send('帮我查原因');
    socket.ctl.add({'type': 'message.start', 'conversation_id': 'c1', 'user_message_id': 'u2', 'title': '旧对话'});
    socket.ctl.add({'type': 'turn.model', 'model': 'smart', 'label': '深度'});
    socket.ctl.add({'type': 'message.done', 'message': {'id': 'a2', 'role': 'assistant', 'blocks': [{'type': 'text', 'text': '好'}]}});
    await tester.pumpAndSettle(); // 生成中的动画不会停：收尾后再等
    expect(find.text('自动 · 深度'), findsOneWidget);
    expect(find.bySemanticsLabel(RegExp('模型：自动 · 深度')), findsOneWidget);
    // 三项 → 弹菜单，“自动”带一行说明
    await tester.tap(find.bySemanticsLabel(RegExp('模型：自动')));
    await tester.pumpAndSettle();
    expect(find.text('简单的事用快速，复杂的用深度，每轮自动挑'), findsOneWidget);
  });
}
