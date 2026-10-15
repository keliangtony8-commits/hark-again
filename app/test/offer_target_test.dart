// 建议卡直达 App 某一页（v0.93）：target = 名字 或 名字:id（后端 app/card_targets.py）。
// - 映射表：每个去处都有路由；'project:<id>' → /projects/<id>，缺 id 退到列表；不认识的名字当没有；
// - 只有去处没有指令的助手卡：眉题“需要你亲自处理”，去处按钮是唯一的主按钮，点了直达那页（不调 start）；
// - 项目去处 + 指令：两颗按钮都在，“打开项目”切到项目页。
// - v0.95 系统提醒（origin 空）只有去处（如“GitHub 连接已失效”）同样眉题“需要你亲自处理”；带指令的系统提醒没有眉题。
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

HomeCard card(String? target, {String? task, bool prompt = true, bool system = false}) => HomeCard.fromJson({
      ...offerJson(),
      if (system) 'origin': null,
      'target': target,
      'task_id': task,
      if (!prompt) 'action_prompt': null,
    });

Future<FakeApi> pump(WidgetTester tester, HomeCard c) async {
  final api = FakeApi();
  final router = GoRouter(initialLocation: '/home', routes: [
    GoRoute(
        path: '/home',
        builder: (_, _) => Scaffold(body: SingleChildScrollView(child: ActionCard(card: c, onDo: (_) {}, onOpen: (_, _, {projectId}) {})))),
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
    for (final name in ['usage', 'tasks', 'memory', 'skills', 'connectors', 'pages', 'project']) {
      expect(cardTarget(name), isNotNull, reason: name);
    }
    expect(cardTarget('vault'), isNull, reason: 'v2.96 保险箱并进连接的账号，后端不再发 vault');
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

  test('eyebrow rules (system alerts too)', () {
    expect(cardEyebrow(card('connectors', prompt: false), cardTarget('connectors')), '需要你亲自处理');
    final sys = card('connectors', prompt: false, system: true);
    expect(sys.offered, isFalse);
    expect(cardEyebrow(sys, cardTarget('connectors')), '需要你亲自处理');
    expect(cardEyebrow(card('usage', system: true), cardTarget('usage')), isNull, reason: '带“去做”的系统提醒不加眉题');
    expect(cardEyebrow(card(null, prompt: false, system: true), null), isNull);
    expect(cardEyebrow(card('usage'), cardTarget('usage')), '可以替你做');
  });

  testWidgets('system "connection expired" alert: eyebrow + reconnect is the primary pill', (tester) async {
    await pump(tester, card('connectors', prompt: false, system: true));
    expect(find.text('需要你亲自处理'), findsOneWidget);
    final pill = tester.widget<PillButton>(find.byWidgetPredicate((w) => w is PillButton && w.label == '去连接的账号'));
    expect(pill.primary, isTrue);
    await tester.tap(find.text('去连接的账号'));
    await tester.pumpAndSettle();
    expect(find.text('CONNECTORS PAGE'), findsOneWidget);
  });

  testWidgets('target-only offer: do-it-yourself eyebrow, one primary pill opens the page', (tester) async {
    final api = await pump(tester, card('connectors', prompt: false));
    expect(find.text('需要你亲自处理'), findsOneWidget);
    expect(find.text('可以替你做'), findsNothing);
    expect(find.text('帮我续费'), findsNothing);
    final pill = tester.widget<PillButton>(find.byWidgetPredicate((w) => w is PillButton && w.label == '去连接的账号'));
    expect(pill.primary, true);
    await tester.tap(find.text('去连接的账号'));
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
