// 建议卡直达 App 某一页（v0.93）：target = 名字 或 名字:id（后端 app/card_targets.py）。
// - 映射表：每个去处都有路由；'project:<id>' → /projects/<id>，缺 id 退到列表；不认识的名字当没有；
// - 只有去处没有指令的助手卡：眉题“需要你亲自处理”，去处按钮是唯一的主按钮，点了直达那页（不调 start）；
// - 项目去处 + 指令：两颗按钮都在，“打开项目”切到项目页。
import 'package:assistant/core/api.dart';
import 'package:assistant/features/home/action_card.dart';
import 'package:assistant/models/resources.dart';
import 'package:assistant/theme/app_theme.dart';
import 'package:assistant/ui/glass.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';

import 'budget_card_test.dart' show FakeApi;
import 'home_offer_test.dart' show offerJson;

HomeCard card(String? target, {String? task, bool prompt = true}) => HomeCard.fromJson({
      ...offerJson(),
      'target': target,
      'task_id': task,
      if (!prompt) 'action_prompt': null,
    });

Future<FakeApi> pump(WidgetTester tester, HomeCard c) async {
  final api = FakeApi();
  final router = GoRouter(initialLocation: '/home', routes: [
    GoRoute(
        path: '/home',
        builder: (_, _) => Scaffold(body: SingleChildScrollView(child: ActionCard(card: c, onDo: (_) {}, onOpen: (_, _) {})))),
    GoRoute(path: '/me/connectors', builder: (_, _) => const Scaffold(body: Text('CONNECTORS PAGE'))),
    GoRoute(path: '/projects/:id', builder: (_, s) => Scaffold(body: Text('PROJECT ${s.pathParameters['id']}'))),
  ]);
  await tester.pumpWidget(ProviderScope(
    overrides: [apiProvider.overrideWithValue(api)],
    child: MaterialApp.router(theme: buildTheme(Brightness.light), routerConfig: router),
  ));
  await tester.pumpAndSettle();
  return api;
}

void main() {
  test('every target maps to a route; ids fill slots', () {
    for (final name in ['usage', 'tasks', 'memory', 'skills', 'connectors', 'vault', 'pages', 'project']) {
      expect(cardTarget(name), isNotNull, reason: name);
    }
    expect(splitTarget('project:abc'), ('project', 'abc'));
    expect(splitTarget('usage'), ('usage', null));
    expect(splitTarget('project:'), ('project', null));
    final p = cardTarget('project:p1')!;
    expect(p.label, '打开项目');
    expect(cardRoute(p, card('project:p1')), '/projects/p1');
    expect(cardRoute(p, card('project')), '/projects');
    expect(cardRoute(cardTarget('connectors')!, card('connectors')), '/me/connectors');
    expect(cardRoute(cardTarget('tasks')!, card('tasks', task: 't1')), '/me/tasks/t1');
    expect(cardTarget('settings:x'), isNull, reason: '不认识的名字当没有');
  });

  testWidgets('target-only offer: do-it-yourself eyebrow, one primary pill opens the page', (tester) async {
    final api = await pump(tester, card('connectors', prompt: false));
    expect(find.text('需要你亲自处理'), findsOneWidget);
    expect(find.text('可以替你做'), findsNothing);
    expect(find.text('帮我续费'), findsNothing);
    final pill = tester.widget<PillButton>(find.byWidgetPredicate((w) => w is PillButton && w.label == '去连接器'));
    expect(pill.primary, true);
    await tester.tap(find.text('去连接器'));
    await tester.pumpAndSettle();
    expect(find.text('CONNECTORS PAGE'), findsOneWidget);
    expect(api.calls.any((c) => c.endsWith('/start')), false);
  });

  testWidgets('project target with prompt: both buttons, 打开项目 goes to project', (tester) async {
    await pump(tester, card('project:p1'));
    expect(find.text('可以替你做'), findsOneWidget);
    expect(find.text('帮我续费'), findsOneWidget);
    await tester.tap(find.text('打开项目'));
    await tester.pumpAndSettle();
    expect(find.text('PROJECT p1'), findsOneWidget);
  });
}
