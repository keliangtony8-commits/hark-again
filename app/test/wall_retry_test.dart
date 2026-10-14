// v2.19 修好就重跑：wall_retrying 解析、碰壁条换成“正在重新运行”（同步图标、没有“重试”，“去处理”还在）、
// withRetried 拼提示、OAuth 回调的 ?retried= 解析、保险箱 / MCP 新建响应里的 retried_note。
import 'package:assistant/core/api.dart';
import 'package:assistant/core/cache.dart';
import 'package:assistant/features/me/connectors_screen.dart';
import 'package:assistant/features/me/task_detail.dart';
import 'package:assistant/features/me/task_wall.dart';
import 'package:assistant/models/resources.dart';
import 'package:assistant/theme/app_theme.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';

import 'task_wall_test.dart' show FakeApi, taskJson;

/// 重跑排上 = 详情页在转圈 / 轮询，pumpAndSettle 等不到头：固定推几帧。
Future<void> pumpRunning(WidgetTester tester, FakeApi api) async {
  final router = GoRouter(initialLocation: '/me/tasks/t1', routes: [
    GoRoute(path: '/me/tasks/:id', builder: (_, s) => TaskDetailScreen(id: s.pathParameters['id']!)),
  ]);
  await tester.pumpWidget(ProviderScope(
    overrides: [apiProvider.overrideWithValue(api), cacheStoreProvider.overrideWithValue(MemoryCacheStore())],
    child: MaterialApp.router(theme: buildTheme(Brightness.light), routerConfig: router),
  ));
  for (var i = 0; i < 10; i++) {
    await tester.pump(const Duration(milliseconds: 100));
  }
}

void main() {
  test('parsing + wording', () {
    final j = {...taskJson(label: '需要登录 jw.example.edu', fixable: true, open: 'vault'), 'run_requested': true, 'wall_retrying': true};
    final t = ScheduledTask.fromJson(j);
    expect(t.wallRetrying, isTrue);
    expect(wallHint(t), contains('已经在重新运行'));
    final waiting = ScheduledTask.fromJson(taskJson(label: '需要登录 jw.example.edu', fixable: true, open: 'vault', output: 'report'));
    expect(waiting.wallRetrying, isFalse);
    expect(wallHint(waiting), contains('自动重新运行'));
    expect(withRetried('已连接 GitHub', null), '已连接 GitHub');
    expect(withRetried('已连接 GitHub', '之前卡在这里的「周报」已重新运行'), '已连接 GitHub。之前卡在这里的「周报」已重新运行');
    final r = OAuthResult.fromQuery({'connected': 'github', 'retried': '之前卡在这里的「周报」已重新运行'})!;
    expect(r.retried, contains('周报'));
    expect(r, isNot(OAuthResult.fromQuery({'connected': 'github'})));
    expect(SecretItem.fromJson({'id': 's', 'name': 'x', 'retried_note': 'n'}).retriedNote, 'n');
    expect(SecretItem.fromJson({'id': 's', 'name': 'x'}).retriedNote, isNull);
    expect(McpServerItem.fromJson({'id': 'm', 'name': 'x', 'retried_note': 'n'}).retriedNote, 'n');
  });

  testWidgets('retrying wall: sync icon, no retry button, still a way to the vault', (tester) async {
    final api = FakeApi({...taskJson(label: '需要登录 jw.example.edu', fixable: true, open: 'vault'), 'run_requested': true, 'wall_retrying': true});
    await pumpRunning(tester, api);
    expect(find.text('需要登录 jw.example.edu'), findsOneWidget);
    expect(find.text('已经在重新运行，成功后这条会自动收起。'), findsOneWidget);
    expect(find.byIcon(Icons.sync_rounded), findsOneWidget);
    expect(find.text('重试'), findsNothing);
    expect(find.text('打开保险箱'), findsOneWidget);
    await tester.pumpWidget(const SizedBox()); // 卸掉页面，停掉轮询计时器
    await tester.pump(const Duration(seconds: 30));
  });
}
