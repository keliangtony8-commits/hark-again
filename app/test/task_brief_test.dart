// v2.13 定时任务的“做法 + 观察 + 没打扰你 + 跳过下一次”：模型解析、文案、详情页“助手记下的”（看全文 / 清空走 PATCH）、
// 没打扰你的运行（静音图标 + 原因）、跳过下一次 / 撤销（POST / DELETE skip）、一次性和定时脚本不出现相应入口。
import 'package:assistant/core/api.dart';
import 'package:assistant/core/cache.dart';
import 'package:assistant/features/me/task_detail.dart';
import 'package:assistant/features/me/task_labels.dart';
import 'package:assistant/models/resources.dart';
import 'package:assistant/theme/app_theme.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';

final _next = DateTime.now().add(const Duration(days: 2)).toUtc().toIso8601String();
final _skipped = DateTime.now().add(const Duration(days: 1)).toUtc().toIso8601String();

Map<String, dynamic> taskJson({String? runbook, String? note, bool skipped = false, String kind = 'agent', String? runAt}) => {
      'id': 't1',
      'name': '机票盯价',
      'prompt': '看看机票价格',
      'cron': runAt == null ? '0 8 * * *' : '',
      'run_at': runAt,
      'active': true,
      'output': 'report',
      'kind': kind,
      'run_requested': false,
      'next_run_at': _next,
      'runbook': runbook,
      'note': note,
      'skipped_at': skipped ? _skipped : null,
    };

Map<String, dynamic> runJson(String id, {String status = 'ok', String? silent}) => {
      'id': id,
      'trigger': 'schedule',
      'status': status,
      'silent_reason': silent,
      'conversation_id': 'c1',
      'started_at': DateTime.now().subtract(const Duration(hours: 1)).toUtc().toIso8601String(),
      'finished_at': DateTime.now().toUtc().toIso8601String(),
      'duration_ms': 9000,
    };

class FakeApi implements Api {
  FakeApi(this.task, [this.runs = const []]);
  Map<String, dynamic> task;
  List<Map<String, dynamic>> runs;
  final calls = <String>[];

  @override
  Future<dynamic> get(String path) async {
    calls.add('GET $path');
    if (path == '/api/tasks') return [task];
    if (path == '/api/tasks/t1/runs') return runs;
    throw UnimplementedError(path);
  }

  @override
  Future<dynamic> post(String path, [Object? body]) async {
    calls.add('POST $path');
    if (path == '/api/tasks/t1/skip') task = {...task, 'skipped_at': _skipped};
    return {'ok': true};
  }

  @override
  Future<dynamic> delete(String path) async {
    calls.add('DELETE $path');
    if (path == '/api/tasks/t1/skip') task = {...task, 'skipped_at': null};
    return {'ok': true};
  }

  @override
  Future<dynamic> patch(String path, Object? body) async {
    calls.add('PATCH $path $body');
    task = {...task, ...(body as Map).map((k, v) => MapEntry(k as String, v == '' ? null : v))};
    return task;
  }

  @override
  dynamic noSuchMethod(Invocation i) => throw UnimplementedError();
}

Future<void> pump(WidgetTester tester, FakeApi api) async {
  final router = GoRouter(initialLocation: '/me/tasks/t1', routes: [
    GoRoute(path: '/me/tasks/:id', builder: (_, s) => TaskDetailScreen(id: s.pathParameters['id']!)),
  ]);
  await tester.pumpWidget(ProviderScope(
    overrides: [apiProvider.overrideWithValue(api), cacheStoreProvider.overrideWithValue(MemoryCacheStore())],
    child: MaterialApp.router(theme: buildTheme(Brightness.light), routerConfig: router),
  ));
  await tester.pumpAndSettle();
}

void main() {
  test('parsing + labels', () {
    final t = ScheduledTask.fromJson(taskJson(runbook: '  1. 打开网站  ', note: '', skipped: true));
    expect(t.runbook, '1. 打开网站');
    expect(t.note, isNull, reason: '空串 = 没有');
    expect(t.skippedAt, isNotNull);
    expect(skipLabel(t), startsWith('跳过了 '));
    expect(t.canSkip, isTrue);
    expect(ScheduledTask.fromJson(taskJson(runAt: _next)).canSkip, isFalse, reason: '一次性任务不跳');
    final quiet = TaskRun.fromJson(runJson('r1', silent: '价格没变'));
    expect(quiet.silent, isTrue);
    expect(runStateLabel(quiet), '没打扰你');
    expect(TaskRun.fromJson(runJson('r2', status: 'error', silent: 'x')).silent, isFalse, reason: '失败优先');
    expect(runStateLabel(TaskRun.fromJson(runJson('r3'))), '成功');
  });

  testWidgets('memo section: shows, opens full text, clears via PATCH', (tester) async {
    final api = FakeApi(taskJson(runbook: '1. 打开 example.com/fares\n2. 记最低价\n3. 对比上周', note: '网站周末很慢'));
    await pump(tester, api);
    expect(find.text('助手记下的'), findsOneWidget);
    expect(find.text('做法'), findsOneWidget);
    expect(find.text('观察'), findsOneWidget);
    await tester.tap(find.text('做法'));
    await tester.pumpAndSettle();
    expect(find.textContaining('3. 对比上周'), findsOneWidget, reason: '弹层里是全文');
    await tester.tap(find.text('清空'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('清空').last);
    await tester.pumpAndSettle();
    expect(api.calls.any((c) => c.startsWith('PATCH /api/tasks/t1') && c.contains('runbook')), isTrue, reason: api.calls.join('\n'));
    expect(find.text('做法'), findsNothing);
    expect(find.text('观察'), findsOneWidget);
  });

  testWidgets('no memo / script → no section', (tester) async {
    await pump(tester, FakeApi(taskJson()));
    expect(find.text('助手记下的'), findsNothing);
    await pump(tester, FakeApi(taskJson(runbook: 'x', kind: 'script')));
    expect(find.text('助手记下的'), findsNothing);
  });

  testWidgets('silent run row shows reason', (tester) async {
    await pump(tester, FakeApi(taskJson(), [runJson('r1', silent: '价格没变，还是 ¥820'), runJson('r2')]));
    expect(find.text('价格没变，还是 ¥820'), findsOneWidget);
    expect(find.byIcon(Icons.notifications_off_outlined), findsOneWidget);
    expect(find.textContaining('没打扰你'), findsOneWidget);
  });

  testWidgets('skip next → undo', (tester) async {
    final api = FakeApi(taskJson());
    await pump(tester, api);
    await tester.tap(find.text('跳过下一次'));
    await tester.pumpAndSettle();
    expect(api.calls, contains('POST /api/tasks/t1/skip'));
    expect(find.textContaining('跳过了 '), findsOneWidget);
    await tester.tap(find.text('撤销跳过'));
    await tester.pumpAndSettle();
    expect(api.calls, contains('DELETE /api/tasks/t1/skip'));
    expect(find.textContaining('跳过了 '), findsNothing);
    expect(find.text('跳过下一次'), findsOneWidget);
  });

  testWidgets('once task has no skip button', (tester) async {
    await pump(tester, FakeApi(taskJson(runAt: _next)));
    expect(find.text('跳过下一次'), findsNothing);
  });
}
