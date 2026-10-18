// 用量页“本月最花钱的对话”：解析（老服务器没有字段 → 空；title=null = 已删）、占比（有定价按钱，否则按 token）；
// 界面：有数据才出这一节；点一行 → 切到 Chat 并打开那个对话；已删的不可点。
import 'package:assistant/core/api.dart';
import 'package:assistant/core/cache.dart';
import 'package:assistant/core/chat_socket.dart';
import 'package:assistant/features/chat/chat_controller.dart';
import 'package:assistant/features/me/usage_screen.dart';
import 'package:assistant/models/usage.dart';
import 'package:assistant/theme/app_theme.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';

import 'chat_controller_test.dart' show FakeSocket;

Map<String, dynamic> report({List<String> priced = const ['fast'], List<Map<String, dynamic>>? convs}) => {
      'currency': 'CNY',
      'budget': null,
      'priced': priced,
      'today': {'calls': 0, 'tokens': 0, 'cost': 0, 'models': []},
      'month': {'calls': 10, 'tokens': 1000, 'cost': 10, 'models': []},
      'conversations': ?convs,
    };

final _convs = [
  {'id': 'a', 'title': '写论文', 'calls': 6, 'tokens': 600, 'cost': 8.0},
  {'id': 'gone', 'title': null, 'calls': 1, 'tokens': 300, 'cost': 1.0},
];

class _Api implements Api {
  _Api(this.body);
  final Map<String, dynamic> body;
  final opened = <String>[];
  @override
  Future<dynamic> get(String path) async {
    if (path == '/api/usage') return body;
    if (path.startsWith('/api/conversations/')) {
      final id = path.split('/').last;
      opened.add(id);
      return {'id': id, 'messages': <dynamic>[]};
    }
    if (path.startsWith('/api/conversations')) return <dynamic>[];
    return null;
  }

  @override
  dynamic noSuchMethod(Invocation i) => throw UnimplementedError();
}

Future<ProviderContainer> _pump(WidgetTester tester, _Api api) async {
  final c = ProviderContainer(overrides: [
    apiProvider.overrideWithValue(api),
    chatSocketProvider.overrideWithValue(FakeSocket()),
    cacheStoreProvider.overrideWithValue(MemoryCacheStore()),
  ]);
  addTearDown(c.dispose);
  final router = GoRouter(initialLocation: '/usage', routes: [
    GoRoute(path: '/usage', builder: (_, _) => const UsageScreen()),
    GoRoute(path: '/chat', builder: (_, _) => const Scaffold(body: Text('CHAT'))),
  ]);
  await tester.pumpWidget(UncontrolledProviderScope(
    container: c,
    child: MaterialApp.router(theme: buildTheme(Brightness.light), routerConfig: router),
  ));
  await tester.pumpAndSettle();
  return c;
}

void main() {
  test('解析与占比', () {
    expect(UsageReport.fromJson(report()).conversations, isEmpty); // 老服务器
    final r = UsageReport.fromJson(report(convs: _convs));
    expect(r.conversations.map((c) => c.id), ['a', 'gone']);
    expect(r.conversations.last.deleted, true);
    expect(r.shareOf(r.conversations.first), closeTo(0.8, 1e-9)); // 按钱
    final t = UsageReport.fromJson(report(priced: [], convs: _convs));
    expect(t.shareOf(t.conversations.last), closeTo(0.3, 1e-9)); // 没定价按 token
    final zero = UsageReport.fromJson({...report(convs: _convs), 'month': {'calls': 0, 'tokens': 0, 'cost': 0}});
    expect(zero.shareOf(zero.conversations.first), 0);
  });

  testWidgets('没有数据就不出这一节', (tester) async {
    await _pump(tester, _Api(report()));
    expect(find.text('本月最花钱的对话'), findsNothing);
  });

  testWidgets('列表行：标题、占比、花费；已删的灰显且不可点；点一行跳进对话', (tester) async {
    final api = _Api(report(convs: _convs));
    final c = await _pump(tester, api);
    expect(find.text('本月最花钱的对话'), findsOneWidget);
    expect(find.text('写论文'), findsOneWidget);
    expect(find.text('已删除的对话 1 个'), findsOneWidget); // 已删的合并成一行
    expect(find.textContaining('占本月 80%'), findsOneWidget);
    expect(find.text('¥8.00'), findsOneWidget);

    expect(find.descendant(of: find.byKey(const Key('top-conv-deleted')), matching: find.byType(InkWell)), findsNothing);
    await tester.tap(find.text('已删除的对话 1 个'));
    await tester.pumpAndSettle();
    expect(find.text('CHAT'), findsNothing);

    await tester.tap(find.text('写论文'));
    await tester.pumpAndSettle();
    expect(find.text('CHAT'), findsOneWidget);
    expect(api.opened, ['a']);
    expect(c.read(chatProvider('')).activeId, 'a');
  });
}
