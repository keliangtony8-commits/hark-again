// v2.15 碰壁：模型解析（wall_label / wall_reason / wall_fixable / wall_open）、运行“碰壁”状态、
// 任务详情的碰壁条（要你处理 → “打开保险箱”直达 + “重试”走 POST run；会自己好的 → 只有说明、没有按钮）、没壁不占地方。
import 'package:assistant/core/api.dart';
import 'package:assistant/core/cache.dart';
import 'package:assistant/features/me/task_detail.dart';
import 'package:assistant/features/me/task_labels.dart';
import 'package:assistant/features/me/task_wall.dart';
import 'package:assistant/models/resources.dart';
import 'package:assistant/theme/app_theme.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';

final _next = DateTime.now().add(const Duration(days: 2)).toUtc().toIso8601String();

Map<String, dynamic> taskJson({String? label, String? reason, bool fixable = false, String? open, String output = 'panel'}) => {
      'id': 't1',
      'name': '成绩面板',
      'prompt': '查教务系统成绩',
      'cron': '0 8 * * *',
      'active': true,
      'output': output,
      'run_requested': false,
      'next_run_at': _next,
      'wall': label == null ? null : 'needs_login:jw.example.edu',
      'wall_label': label,
      'wall_reason': reason,
      'wall_fixable': fixable,
      'wall_open': open,
    };

Map<String, dynamic> runJson(String id, {String status = 'ok', String? wall, String? error}) => {
      'id': id,
      'trigger': 'schedule',
      'status': status,
      'error': error,
      'wall': wall,
      'wall_label': wall == null ? null : '需要登录 jw.example.edu',
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
    return {'ok': true};
  }

  @override
  dynamic noSuchMethod(Invocation i) => throw UnimplementedError();
}

Future<void> pump(WidgetTester tester, FakeApi api) async {
  final router = GoRouter(initialLocation: '/me/tasks/t1', routes: [
    GoRoute(path: '/me/tasks/:id', builder: (_, s) => TaskDetailScreen(id: s.pathParameters['id']!)),
    GoRoute(path: '/me/vault', builder: (_, _) => const Scaffold(body: Text('保险箱页'))),
  ]);
  await tester.pumpWidget(ProviderScope(
    overrides: [apiProvider.overrideWithValue(api), cacheStoreProvider.overrideWithValue(MemoryCacheStore())],
    child: MaterialApp.router(theme: buildTheme(Brightness.light), routerConfig: router),
  ));
  await tester.pumpAndSettle();
}

void main() {
  test('parsing + labels', () {
    final t = ScheduledTask.fromJson(taskJson(label: '需要登录 jw.example.edu', reason: '没有学号密码', fixable: true, open: 'vault'));
    expect(t.walled, isTrue);
    expect(t.wallFixable, isTrue);
    expect(t.wallOpen, 'vault');
    expect(wallHint(t), contains('上一次的内容'));
    final ok = ScheduledTask.fromJson(taskJson());
    expect(ok.walled, isFalse);
    expect(ok.wallFixable, isFalse);
    expect(wallHint(ScheduledTask.fromJson(taskJson(label: '暂时被挡住（captcha），之后会再试'))), contains('自动再试'));
    final r = TaskRun.fromJson(runJson('r1', status: 'error', wall: 'needs_login:jw.example.edu', error: '需要登录 jw.example.edu：没有学号密码'));
    expect(r.walled, isTrue);
    expect(runStateLabel(r), '碰壁');
    expect(runStateLabel(TaskRun.fromJson(runJson('r2', status: 'error', error: 'x'))), '失败');
  });

  testWidgets('fixable wall: notice, go to vault, retry runs task', (tester) async {
    final api = FakeApi(taskJson(label: '需要登录 jw.example.edu', reason: '登录页要学号密码', fixable: true, open: 'vault'),
        [runJson('r1', status: 'error', wall: 'needs_login:jw.example.edu', error: '需要登录 jw.example.edu：登录页要学号密码')]);
    await pump(tester, api);
    expect(find.text('需要登录 jw.example.edu'), findsOneWidget);
    expect(find.text('登录页要学号密码'), findsOneWidget);
    expect(find.byIcon(Icons.lock_outline_rounded), findsWidgets, reason: '条子 + 运行行');
    expect(find.textContaining('碰壁'), findsWidgets);
    await tester.tap(find.text('重试'));
    await tester.pumpAndSettle();
    expect(api.calls, contains('POST /api/tasks/t1/run'));
    await tester.tap(find.text('打开保险箱'));
    await tester.pumpAndSettle();
    expect(find.text('保险箱页'), findsOneWidget);
  });

  testWidgets('transient wall: no buttons', (tester) async {
    await pump(tester, FakeApi(taskJson(label: '暂时被挡住（captcha），之后会再试', reason: '出了验证码')));
    expect(find.text('暂时被挡住（captcha），之后会再试'), findsOneWidget);
    expect(find.text('不用你管，下次会自动再试。'), findsOneWidget);
    expect(find.text('重试'), findsNothing);
  });

  testWidgets('no wall: nothing', (tester) async {
    await pump(tester, FakeApi(taskJson()));
    expect(find.byType(WallNotice), findsOneWidget);
    expect(find.text('重试'), findsNothing);
    expect(find.text('不用你管，下次会自动再试。'), findsNothing);
  });
}
