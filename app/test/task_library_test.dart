// 定时任务页（v0.77）：分组 / 摘要 / 下一个 的纯逻辑；页面分组标题、页头、空态起步模板预填新建表单。
import 'package:assistant/core/api.dart';
import 'package:assistant/features/me/task_library.dart';
import 'package:assistant/features/me/tasks_screen.dart';
import 'package:assistant/models/resources.dart';
import 'package:assistant/theme/app_theme.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';

Map<String, dynamic> j(String id,
        {bool active = true, String output = 'report', String? last, bool done = false, DateTime? next, bool requested = false}) =>
    {
      'id': id,
      'name': id,
      'prompt': 'p',
      'cron': '0 8 * * *',
      'active': active,
      'output': output,
      'run_requested': requested,
      'last_status': last,
      'done': done,
      'next_run_at': next?.toUtc().toIso8601String(),
    };

ScheduledTask t(String id, {bool active = true, String output = 'report', String? last, bool done = false, DateTime? next, bool requested = false}) =>
    ScheduledTask.fromJson(j(id, active: active, output: output, last: last, done: done, next: next, requested: requested));

class FakeApi implements Api {
  FakeApi(this.tasks);
  final List<Map<String, dynamic>> tasks;

  @override
  Future<dynamic> get(String path) async => tasks;

  @override
  dynamic noSuchMethod(Invocation i) => throw UnimplementedError();
}

Future<void> pump(WidgetTester tester, List<Map<String, dynamic>> tasks) async {
  tester.view.devicePixelRatio = 1;
  tester.view.physicalSize = const Size(420, 1400);
  addTearDown(tester.view.reset);
  final router = GoRouter(initialLocation: '/me/tasks', routes: [
    GoRoute(path: '/me/tasks', builder: (_, _) => const TasksScreen()),
  ]);
  await tester.pumpWidget(ProviderScope(
    overrides: [apiProvider.overrideWithValue(FakeApi(tasks))],
    child: MaterialApp.router(theme: buildTheme(Brightness.light), routerConfig: router),
  ));
  await tester.pumpAndSettle();
}

void main() {
  final now = DateTime(2026, 10, 11, 9, 0);

  test('groupTasks: 失败在前、面板单列、停下的最后；组内按下次运行', () {
    final list = [
      t('late', next: now.add(const Duration(hours: 5))),
      t('early', next: now.add(const Duration(hours: 1))),
      t('bad', last: 'error', next: now.add(const Duration(hours: 2))),
      t('retrying', last: 'error', requested: true),
      t('panel', output: 'panel', next: now.add(const Duration(hours: 3))),
      t('off', active: false, last: 'error'),
      t('done', done: true),
    ];
    final g = groupTasks(list);
    expect(g.attention.map((x) => x.id), ['bad']);
    expect(g.running.map((x) => x.id), ['early', 'late', 'retrying']);
    expect(g.panels.map((x) => x.id), ['panel']);
    expect(g.idle.map((x) => x.id), ['off', 'done']);
  });

  test('taskSummary / nextUp', () {
    expect(taskSummary(const []), '到点我自己去做的事');
    expect(taskSummary([t('a'), t('b')]), '2 个任务 · 全部在跑');
    expect(taskSummary([t('a', last: 'error'), t('b', active: false)]), '2 个任务 · 1 个在跑 · 1 个需要留意');
    expect(nextUp(const [], now: now), isNull);
    final list = [
      t('later', next: DateTime(2026, 10, 12, 8, 0)),
      t('paused', active: false, next: DateTime(2026, 10, 11, 9, 30)),
      t('soon', next: DateTime(2026, 10, 11, 21, 0)),
    ];
    expect(nextUp(list, now: now), ('soon', '今天 21:00'));
    expect(nextUp([t('now', next: now.add(const Duration(seconds: 20)))], now: now), ('now', '马上'));
  });

  testWidgets('页面：分组标题 + 页头摘要', (tester) async {
    await pump(tester, [
      j('早间简报', next: DateTime.now().add(const Duration(hours: 2))),
      j('新闻', last: 'error'),
      j('天气', output: 'panel'),
      j('旧提醒', active: false),
    ]);
    for (final s in ['需要留意', '在跑', 'Home 面板', '已停下', '4 个任务 · 3 个在跑 · 1 个需要留意']) {
      expect(find.text(s), findsOneWidget, reason: s);
    }
    expect(find.textContaining('下一个：早间简报'), findsOneWidget);
  });

  testWidgets('空列表：起步模板打开预填的新建表单', (tester) async {
    await pump(tester, const []);
    expect(find.text('还没有定时任务'), findsOneWidget);
    await tester.tap(find.text('每周复盘'));
    await tester.pumpAndSettle();
    expect(find.text('新定时任务'), findsOneWidget);
    expect(find.widgetWithText(TextField, '每周复盘'), findsOneWidget);
    expect(find.text('每周日 21:00'), findsOneWidget); // 模板的 cron 不在常用项里，也作为一颗选中
  });
}
