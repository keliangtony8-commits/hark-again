// 预算提醒卡：target 解析、去处映射（未知值忽略）、“查看用量”跳到用量页并标已读、忽略后刷新未读。
import 'package:assistant/core/api.dart';
import 'package:assistant/features/home/action_card.dart';
import 'package:assistant/models/resources.dart';
import 'package:assistant/theme/app_theme.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';

Map<String, dynamic> cardJson({String? target = 'usage', bool unread = true}) => {
      'id': 'k1',
      'kind': 'action',
      'title': '本月模型花费已到预算的 80%',
      'blocks': [
        {'type': 'text', 'text': '本月已用 **¥8.10**，预算 ¥10.00（81%）。'}
      ],
      'action_prompt': '看看花在哪',
      'target': target,
      'dismissed': false,
      'unread': unread,
    };

class FakeApi implements Api {
  final calls = <String>[];
  Object? readBody;
  /// POST /api/cards/{id}/start 的回复（建议卡开始做）；cards 列表 GET 回的卡
  Map<String, dynamic> startReply = {'conversation_id': 'c9', 'prompt': '去续费校园网一个月', 'started': true};
  Map<String, dynamic>? listed;

  @override
  Future<dynamic> get(String path) async {
    calls.add('GET $path');
    if (path == '/api/inbox') return {'unread': 0, 'latest': null};
    return <dynamic>[listed ?? cardJson()];
  }

  @override
  Future<dynamic> post(String path, [Object? body]) async {
    calls.add('POST $path');
    if (path.endsWith('/start')) return startReply;
    readBody = body;
    return {'unread': 0, 'latest': null};
  }

  @override
  Future<dynamic> patch(String path, [Object? body]) async {
    calls.add('PATCH $path $body');
    return {...cardJson(), 'dismissed': true};
  }

  @override
  dynamic noSuchMethod(Invocation i) => throw UnimplementedError();
}

Future<FakeApi> pump(WidgetTester tester, Map<String, dynamic> json,
    {List<String>? sent, List<(String, String?)>? opened, FakeApi? fake}) async {
  final api = fake ?? FakeApi();
  final router = GoRouter(initialLocation: '/home', routes: [
    GoRoute(
        path: '/home',
        builder: (_, _) => Scaffold(
            body: SingleChildScrollView(child: ActionCard(
                card: HomeCard.fromJson(json), onDo: (t) => sent?.add(t), onOpen: (id, s, {projectId}) => opened?.add((id, s)))))),
    GoRoute(path: '/me/usage', builder: (_, _) => const Scaffold(body: Text('USAGE PAGE'))),
  ]);
  await tester.pumpWidget(ProviderScope(
    overrides: [apiProvider.overrideWithValue(api)],
    child: MaterialApp.router(theme: buildTheme(Brightness.light), routerConfig: router),
  ));
  await tester.pumpAndSettle();
  return api;
}

void main() {
  test('target parsing and mapping', () {
    expect(HomeCard.fromJson(cardJson()).target, 'usage');
    expect(HomeCard.fromJson(cardJson(target: null)).target, isNull);
    expect(cardTarget('usage')?.route, '/me/usage');
    expect(cardTarget('something-new'), isNull, reason: '老客户端遇到新去处：当没有');
    expect(cardTarget(null), isNull);
  });

  testWidgets('查看用量 marks read and opens usage page', (tester) async {
    final api = await pump(tester, cardJson());
    expect(find.text('本月模型花费已到预算的 80%'), findsOneWidget);
    expect(find.text('去做'), findsOneWidget);
    await tester.tap(find.text('查看用量'));
    await tester.pumpAndSettle();
    expect(find.text('USAGE PAGE'), findsOneWidget);
    expect(api.calls, contains('POST /api/inbox/read'));
    expect(api.readBody, {'ids': ['k1']});
  });

  testWidgets('already read: no read call; 去做 sends prompt', (tester) async {
    final sent = <String>[];
    final api = await pump(tester, cardJson(unread: false), sent: sent);
    await tester.tap(find.text('去做'));
    expect(sent, ['看看花在哪']);
    await tester.tap(find.text('查看用量'));
    await tester.pumpAndSettle();
    expect(api.calls.where((c) => c.startsWith('POST')), isEmpty);
  });

  testWidgets('unknown target: no extra button; 忽略 dismisses and refreshes inbox', (tester) async {
    final api = await pump(tester, cardJson(target: 'future-thing'));
    expect(find.byType(OutlinedButton), findsNothing);
    await tester.tap(find.text('忽略'));
    await tester.pumpAndSettle();
    expect(api.calls.any((c) => c.startsWith('PATCH /api/cards/k1')), true);
    expect(api.calls, contains('GET /api/inbox'));
  });
}
