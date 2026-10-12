// 定时任务运行记录：模型解析、钟点/耗时格式、提醒卡去处（{task} 换成任务 id）、
// 列表页“上次失败”、详情页三种状态 + 失败原因、运行中轮询直到结束就停、立即运行、任务不在了。
import 'package:assistant/core/api.dart';
import 'package:assistant/core/cache.dart';
import 'package:assistant/features/home/action_card.dart';
import 'package:assistant/features/me/task_detail.dart';
import 'package:assistant/features/me/tasks_screen.dart';
import 'package:assistant/models/resources.dart';
import 'package:assistant/theme/app_theme.dart';
import 'package:assistant/theme/tokens.dart';
import 'package:assistant/ui/format.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';

Map<String, dynamic> taskJson({bool requested = false, String? last = 'error'}) => {
      'id': 't1',
      'name': '每日新闻',
      'prompt': '总结今天的新闻',
      'cron': '0 8 * * *',
      'active': true,
      'output': 'report',
      'run_requested': requested,
      'last_status': last,
    };

Map<String, dynamic> runJson(String id, String status, {String? error, String? conv, String trigger = 'schedule'}) => {
      'id': id,
      'trigger': trigger,
      'status': status,
      'error': error,
      'conversation_id': conv,
      'started_at': DateTime.now().subtract(const Duration(minutes: 5)).toUtc().toIso8601String(),
      'finished_at': status == 'running' ? null : DateTime.now().toUtc().toIso8601String(),
      'duration_ms': status == 'running' ? null : 12000,
    };

class FakeApi implements Api {
  FakeApi({required this.tasks, required this.runs});
  List<Map<String, dynamic>> tasks;
  List<Map<String, dynamic>> runs;
  final calls = <String>[];

  @override
  Future<dynamic> get(String path) async {
    calls.add('GET $path');
    if (path == '/api/tasks') return tasks;
    if (path == '/api/tasks/t1/runs') return runs;
    throw UnimplementedError(path);
  }

  @override
  Future<dynamic> post(String path, [Object? body]) async {
    calls.add('POST $path');
    tasks = [taskJson(requested: true)];
    return {'ok': true};
  }

  @override
  dynamic noSuchMethod(Invocation i) => throw UnimplementedError();
}

Future<void> pump(WidgetTester tester, FakeApi api, String location) async {
  final router = GoRouter(initialLocation: location, routes: [
    GoRoute(path: '/me/tasks', builder: (_, _) => const TasksScreen(), routes: [
      GoRoute(path: ':id', builder: (_, s) => TaskDetailScreen(id: s.pathParameters['id']!)),
    ]),
  ]);
  await tester.pumpWidget(ProviderScope(
    overrides: [apiProvider.overrideWithValue(api), cacheStoreProvider.overrideWithValue(MemoryCacheStore())],
    child: MaterialApp.router(theme: buildTheme(Brightness.light), routerConfig: router),
  ));
  await tester.pumpAndSettle();
}

int runFetches(FakeApi api) => api.calls.where((c) => c == 'GET /api/tasks/t1/runs').length;

void main() {
  test('parsing', () {
    final t = ScheduledTask.fromJson(taskJson());
    expect(t.lastFailed, isTrue);
    expect(ScheduledTask.fromJson(taskJson(last: null)).lastStatus, isNull);
    final r = TaskRun.fromJson(runJson('r', 'error', error: '401', trigger: 'manual'));
    expect([r.failed, r.running, r.manual, r.durationMs, r.error], [true, false, true, 12000, '401']);
    expect(TaskRun.fromJson(runJson('r', 'running')).running, isTrue);
    expect(taskBusy(ScheduledTask.fromJson(taskJson()), [r]), isFalse);
    expect(taskBusy(ScheduledTask.fromJson(taskJson(requested: true)), const []), isTrue);
  });

  test('formatWhen / formatDuration', () {
    final now = DateTime(2026, 10, 11, 9, 30);
    expect(formatWhen(DateTime(2026, 10, 11, 8, 5), now: now), '今天 08:05');
    expect(formatWhen(DateTime(2026, 10, 10, 23, 0), now: now), '昨天 23:00');
    expect(formatWhen(DateTime(2026, 9, 1, 8, 0), now: now), '9月1日 08:00');
    expect(formatWhen(DateTime(2025, 12, 31, 8, 0), now: now), '2025年12月31日 08:00');
    expect(formatDuration(300), '不到 1 秒');
    expect(formatDuration(12000), '12 秒');
    expect(formatDuration(120000), '2 分');
    expect(formatDuration(185000), '3 分 5 秒');
    expect(formatDuration(3720000), '1 小时 2 分');
  });

  test('card target for task alerts', () {
    final t = cardTarget('tasks')!;
    HomeCard card(String? task) => HomeCard.fromJson({'id': 'c', 'kind': 'action', 'title': 'x', 'blocks': [], 'task_id': task, 'target': 'tasks', 'dismissed': false});
    expect(cardRoute(t, card('t1')), '/me/tasks/t1');
    expect(cardRoute(t, card(null)), '/me/tasks');
    expect(cardRoute(cardTarget('usage')!, card('t1')), '/me/usage');
  });

  testWidgets('list shows last failure and opens detail', (tester) async {
    final api = FakeApi(tasks: [taskJson()], runs: [runJson('r1', 'error', error: '模型调用失败：401')]);
    await pump(tester, api, '/me/tasks');
    // v1.06：失败和自动暂停一样，问题字在前染警示色（RowTile.problem），计划在后
    expect(find.byWidgetPredicate((w) => w is RichText && w.text.toPlainText() == '上次失败 · 每天 08:00'), findsOneWidget);
    expect(find.bySemanticsLabel(RegExp('上次运行失败')), findsOneWidget);
    await tester.tap(find.text('每日新闻'));
    await tester.pumpAndSettle();
    expect(find.text('运行记录'), findsOneWidget);
    expect(find.text('模型调用失败：401'), findsOneWidget);
  });

  testWidgets('detail rows: ok / error with reason / openable', (tester) async {
    final api = FakeApi(tasks: [taskJson(last: 'ok')], runs: [
      runJson('r2', 'ok', conv: 'c2', trigger: 'manual'),
      runJson('r1', 'error', error: 'RuntimeError: 工具炸了'),
    ]);
    await pump(tester, api, '/me/tasks/t1');
    expect(find.text('每日新闻'), findsOneWidget); // AppBar
    expect(find.text('总结今天的新闻'), findsOneWidget);
    expect(find.text('手动 · 用时 12 秒'), findsOneWidget);
    expect(find.text('定时 · 用时 12 秒'), findsOneWidget);
    expect(find.text('RuntimeError: 工具炸了'), findsOneWidget);
    expect(find.bySemanticsLabel(RegExp(r'^成功.*点按打开报告$')), findsOneWidget);
    expect(find.bySemanticsLabel(RegExp(r'^失败.*原因：RuntimeError')), findsOneWidget);
    expect(find.text('立即运行'), findsOneWidget);
  });

  testWidgets('run now → queued → running → polls until done, then stops', (tester) async {
    final api = FakeApi(tasks: [taskJson(last: 'ok')], runs: [runJson('r1', 'ok')]);
    await pump(tester, api, '/me/tasks/t1');
    await tester.tap(find.text('立即运行'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 500)); // 排队行有循环脉冲，不能 pumpAndSettle
    expect(api.calls, contains('POST /api/tasks/t1/run'));
    expect(find.text('排队中'), findsOneWidget);
    expect(find.text('运行中…'), findsOneWidget);

    // worker 领走：记录里出现 running，任务不再 requested
    api.tasks = [taskJson(last: 'ok')];
    api.runs = [runJson('r2', 'running', trigger: 'manual'), runJson('r1', 'ok')];
    await tester.pump(Timing.taskRunPoll);
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 500));
    expect(find.text('排队中'), findsNothing);
    expect(find.text('手动 · 进行中'), findsOneWidget);

    // 跑完：再刷新一次后停止轮询
    api.runs = [runJson('r2', 'ok', trigger: 'manual', conv: 'c2'), runJson('r1', 'ok')];
    await tester.pump(Timing.taskRunPoll);
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 500));
    expect(find.text('手动 · 用时 12 秒'), findsOneWidget);
    expect(find.text('立即运行'), findsOneWidget);
    final n = runFetches(api);
    await tester.pump(Timing.taskRunPoll * 3);
    await tester.pump();
    expect(runFetches(api), n, reason: '都结束了就不再轮询');
    await tester.pumpWidget(const SizedBox()); // 拆掉页面，确认计时器已清
  });

  testWidgets('empty history', (tester) async {
    final api = FakeApi(tasks: [taskJson(last: null)], runs: []);
    await pump(tester, api, '/me/tasks/t1');
    expect(find.text('还没运行过'), findsOneWidget);
  });

  testWidgets('missing task', (tester) async {
    final gone = FakeApi(tasks: [], runs: []);
    await pump(tester, gone, '/me/tasks/t1');
    expect(find.text('这个任务已经不在了'), findsOneWidget);
  });
}
