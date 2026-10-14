// 主页“今天”（v1.01）：cron 今天的时刻、一次性任务只算今天的；面板与手动停的不进；自动暂停的进且标“已暂停”；
// v2.78 TodayCard：没有任务整张不画；“每天早上的简报”在新面板弹层里。
// 跑过的看结果（完成/失败），到点没跑 = 进行中，之后第一个 = 下一个；摘要；行：问题字、过去的变淡、点行进详情。
import 'package:assistant/core/api.dart';
import 'package:assistant/core/cron.dart';
import 'package:assistant/features/home/new_panel.dart';
import 'package:assistant/features/home/today_card.dart';
import 'package:assistant/features/home/today_agenda.dart';
import 'package:assistant/models/resources.dart';
import 'package:assistant/theme/app_theme.dart';
import 'package:assistant/ui/motion.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';

final now = DateTime(2026, 10, 12, 12, 0); // 周一中午

ScheduledTask task(String id, String cron,
        {bool active = true, String output = 'report', String? last, DateTime? lastRun, String? reason, int streak = 0, DateTime? runAt, bool done = false, bool requested = false, String prompt = 'p'}) =>
    ScheduledTask.fromJson({
      'id': id, 'name': '任务$id', 'prompt': prompt, 'cron': cron, 'active': active, 'output': output, 'run_requested': requested,
      'last_status': last, 'last_run_at': lastRun?.toUtc().toIso8601String(), 'paused_reason': reason, 'fail_streak': streak,
      'run_at': runAt?.toUtc().toIso8601String(), 'done': done,
    });

void main() {
  test('cronTodayAt', () {
    expect(cronTodayAt('30 8 * * *', now), DateTime(2026, 10, 12, 8, 30));
    expect(cronTodayAt('0 9 * * 1-5', now), isNotNull);
    expect(cronTodayAt('0 9 * * 0,6', now), isNull);
    expect(cronTodayAt('0 9 * * 1', now), isNotNull);
    expect(cronTodayAt('0 9 12 * *', now), isNotNull);
    expect(cronTodayAt('0 9 13 * *', now), isNull);
    expect(cronTodayAt('5 * * * *', now), isNull, reason: '每小时不算今天的一件事');
    expect(cronTodayAt('bad', now), isNull);
    expect(cronTodayAt('0 9 * * 7', DateTime(2026, 10, 11)), isNotNull, reason: '7 也是周日');
  });

  test('哪些进日程、什么状态、怎么排', () {
    final items = todayAgenda([
      task('later', '0 21 * * *'),
      task('done', '0 8 * * *', last: 'ok', lastRun: DateTime(2026, 10, 12, 8, 1)),
      task('fail', '0 9 * * *', last: 'error', lastRun: DateTime(2026, 10, 12, 9, 0), streak: 1),
      task('due', '0 11 * * *', last: 'ok', lastRun: DateTime(2026, 10, 11, 11, 0)), // 昨天跑过，今天到点还没跑
      task('next', '0 18 * * *'),
      task('paused', '0 7 * * *', active: false, reason: 'failures', streak: 3),
      task('stopped', '0 7 * * *', active: false),
      task('panel', '0 10 * * *', output: 'panel'),
      task('hourly', '0 * * * *'),
      task('once', '', runAt: DateTime(2026, 10, 12, 15, 0)),
      task('onceDone', '', runAt: DateTime(2026, 10, 12, 6, 0), done: true, last: 'ok', lastRun: DateTime(2026, 10, 12, 6, 0), active: false),
      task('tomorrow', '', runAt: DateTime(2026, 10, 13, 8, 0)),
    ], now);
    expect([for (final i in items) '${i.time} ${i.task.id} ${i.state.name}'], [
      '06:00 onceDone done',
      '07:00 paused paused',
      '08:00 done done',
      '09:00 fail failed',
      '11:00 due running',
      '15:00 once next',
      '18:00 next later',
      '21:00 later later',
    ]);
    expect(agendaSummary(items), '还剩 4 件 · 下一个 15:00');
    expect(agendaProblem(items[1]), '已暂停');
    expect(agendaDetail(items[1]), '连续失败 3 次，今天不会跑');
    expect(agendaProblem(items[3]), '失败');
    expect([agendaHint(items[0]), agendaHint(items[4]), agendaHint(items[5]), agendaHint(items[6])], ['已完成', '进行中…', '下一个', '']);
    expect([agendaDetail(items[2]), agendaDetail(items[5])], ['每天', '一次性']);
  });

  test('摘要：空 / 都跑完', () {
    expect(agendaSummary(const []), '今天没有排定的任务');
    final all = todayAgenda([task('a', '0 8 * * *', last: 'ok', lastRun: DateTime(2026, 10, 12, 8))], now);
    expect(agendaSummary(all), '今天的 1 件都跑完了');
    expect(todayAgenda([task('q', '0 20 * * *', requested: true)], now).single.state, AgendaState.running);
  });

  Future<List<String>> pumpToday(WidgetTester tester, List<ScheduledTask> tasks) async {
    final pushed = <String>[];
    final router = GoRouter(initialLocation: '/home', routes: [
      GoRoute(
          path: '/home',
          builder: (_, _) =>
              Scaffold(body: SingleChildScrollView(child: TodayCard(tasks: tasks)))),
      GoRoute(path: '/me/tasks', builder: (_, _) { pushed.add('/me/tasks'); return const Text('TASKS'); }, routes: [
        GoRoute(path: ':id', builder: (_, s) { pushed.add('/me/tasks/${s.pathParameters['id']}'); return const Text('DETAIL'); }),
      ]),
    ]);
    await tester.pumpWidget(ProviderScope(
      overrides: [apiProvider.overrideWith((_) => throw UnimplementedError())],
      child: MaterialApp.router(theme: buildTheme(Brightness.light), routerConfig: router),
    ));
    await tester.pumpAndSettle();
    return pushed;
  }

  testWidgets('空：整张卡不画（没有空状态、没有重复摘要）', (tester) async {
    await pumpToday(tester, const []);
    expect(find.text('今天'), findsNothing);
    expect(find.text('今天没有排定的任务'), findsNothing);
  });

  testWidgets('有任务：卡头“今天” + 摘要', (tester) async {
    await pumpToday(tester, [task('b', '59 23 * * *')]);
    expect(find.text('今天'), findsOneWidget);
    expect(find.textContaining('还剩 1 件'), findsOneWidget);
  });

  test('早间简报：哪些算已经排了', () {
    expect(morningBrief.prompt, prepDayPrompt);
    expect(morningBrief.cron, '0 7 * * *');
    expect(briefTaskOf([task('a', '0 7 * * *', prompt: '帮我准备今天')])?.id, 'a');
    expect(briefTaskOf([task('o', '0 8 * * *', prompt: '帮我准备今天：天气、日程、待办')])?.id, 'o', reason: '老模板也算');
    expect(briefTaskOf([task('x', '0 7 * * *', prompt: '查天气')]), isNull);
    expect(briefTaskOf([task('s', '0 7 * * *', prompt: '帮我准备今天', active: false)]), isNull, reason: '手动停了可以再排');
    expect(briefTaskOf([task('p', '0 7 * * *', prompt: '帮我准备今天', active: false, reason: 'failures', streak: 3)])?.id, 'p');
    expect(briefTaskOf([task('w', '0 7 * * *', prompt: '帮我准备今天', output: 'panel')]), isNull);
    expect(briefTaskOf([task('once', '', prompt: '帮我准备今天', runAt: now)]), isNull);
  });

  testWidgets('新面板弹层：“每天早上的简报”没排时出、点了回调；排好后不出', (tester) async {
    var scheduled = 0;
    Future<void> pumpExtras(bool missing) => tester.pumpWidget(MaterialApp(
        theme: buildTheme(Brightness.light),
        home: Scaffold(
            body: NewPanelExtras(
                briefMissing: missing, removed: const [], onIdea: (_) {}, onBrief: () => scheduled++, onRevive: (_) {}))));
    await pumpExtras(true);
    await tester.pumpAndSettle();
    await tester.tap(find.text(briefIdeaLabel));
    expect(scheduled, 1);
    await pumpExtras(false);
    await tester.pumpAndSettle();
    expect(find.text(briefIdeaLabel), findsNothing);
  });

  test('只有跑完的变淡，失败的不淡（警示字要看得见）', () {
    final today = DateTime.now();
    final noon = DateTime(today.year, today.month, today.day, 12);
    final items = todayAgenda([
      task('a', '0 8 * * *', last: 'ok', lastRun: DateTime(today.year, today.month, today.day, 8, 1)),
      task('b', '0 9 * * *', last: 'error', lastRun: DateTime(today.year, today.month, today.day, 9, 1)),
    ], noon);
    expect(items.map((i) => i.state), [AgendaState.done, AgendaState.failed]);
    expect(items.map((i) => i.faded), [true, false]);
  });

  testWidgets('行：钟点、跑完变淡、点行进详情', (tester) async {
    // 用真实“现在”：一件昨天就该跑过的（今天 00:00，已跑）+ 一件今天 23:59 的
    final today = DateTime.now();
    final pushed = await pumpToday(tester, [
      task('a', '0 0 * * *', last: 'ok', lastRun: DateTime(today.year, today.month, today.day, 0, 1)),
      task('b', '59 23 * * *'),
    ]);
    expect(find.text('00:00'), findsOneWidget);
    expect(find.text('23:59'), findsOneWidget);
    expect(find.text('已完成'), findsOneWidget);
    expect(find.text('下一个'), findsOneWidget);
    final dims = tester.widgetList<Dimmed>(find.byType(Dimmed)).map((d) => d.dimmed).toList();
    expect(dims, [true, false]);
    expect(find.text('现在'), findsOneWidget, reason: '两件之间画一条“现在”');
    expect(find.byWidgetPredicate((w) => w is Semantics && (w.properties.label ?? '').startsWith('现在 ')), findsOneWidget);
    await tester.tap(find.text('任务b'));
    await tester.pumpAndSettle();
    expect(pushed, ['/me/tasks/b']);
  });

  test('“现在”标记：插在第一件还没到点的前面；全在前或全在后不画', () {
    final items = todayAgenda([task('a', '0 8 * * *'), task('b', '0 11 * * *'), task('c', '0 15 * * *'), task('d', '0 21 * * *')], now);
    expect(agendaNowAt(items, now), 2);
    expect(agendaNowAt(items, DateTime(2026, 10, 12, 7)), isNull, reason: '全在后');
    expect(agendaNowAt(items, DateTime(2026, 10, 12, 22)), isNull, reason: '全在前');
    expect(agendaNowAt(items, DateTime(2026, 10, 12, 15)), 3, reason: '正好到点的算已过');
    expect(agendaNowAt(const [], now), isNull);
    expect(clockOf(DateTime(2026, 1, 1, 7, 5)), '07:05');
  });
}
