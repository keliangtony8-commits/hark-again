// 连续失败升级（v0.99）：解析 fail_streak / paused_reason；文案（连续失败 N 次 / 已暂停）；
// 自动暂停的任务进“需要留意”、不变淡、摘要算“需要留意”不算“在跑”；手动停的照旧进“已停下”；
// 列表行只把问题字染警示色；详情页说明条，打开开关恢复后说明条收起。
import 'package:assistant/features/me/task_labels.dart';
import 'package:assistant/features/me/task_library.dart';
import 'package:assistant/models/resources.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'task_runs_test.dart' show FakeApi, pump, runJson, taskJson;

Map<String, dynamic> paused({int streak = 3, String? reason = 'failures', bool active = false}) =>
    {...taskJson(), 'active': active, 'fail_streak': streak, 'paused_reason': reason};

class PatchApi extends FakeApi {
  PatchApi({required super.tasks, required super.runs});

  @override
  Future<dynamic> patch(String path, [Object? body]) async {
    calls.add('PATCH $path $body');
    final t = {...tasks.first, ...(body as Map).cast<String, dynamic>(), 'paused_reason': null, 'fail_streak': 0};
    tasks = [t];
    return t;
  }
}

void main() {
  ScheduledTask t(Map<String, dynamic> j) => ScheduledTask.fromJson(j);

  test('解析与文案', () {
    final p = t(paused());
    expect([p.failStreak, p.pausedReason, p.autoPaused], [3, 'failures', isTrue]);
    expect(t(taskJson()).failStreak, 0); // 老服务器没有这个字段
    expect(taskStateLabel(p), '连续失败 3 次，已暂停');
    expect(nextRunLabel(p), '连续失败，已暂停');
    expect(autoPauseNote(p), contains('连着失败了 3 次'));
    expect(taskStateLabel(t({...taskJson(), 'fail_streak': 2})), '连续失败 2 次');
    expect(taskStateLabel(t({...taskJson(), 'fail_streak': 1})), '上次失败');
    final manual = t(paused(reason: null));
    expect([manual.autoPaused, nextRunLabel(manual), autoPauseNote(manual)], [isFalse, '已暂停', isNull]);
    // 启用着但 paused_reason 还没清（理论上不会）：不算自动暂停
    expect(t(paused(active: true)).autoPaused, isFalse);
  });

  test('分组与摘要', () {
    final list = [
      t({...paused(), 'id': 'a'}),
      t({...paused(reason: null), 'id': 'b'}),
      t({...taskJson(last: 'ok'), 'id': 'c'}),
    ];
    final g = groupTasks(list);
    expect(g.attention.map((x) => x.id), ['a']);
    expect(g.idle.map((x) => x.id), ['b']);
    expect(g.running.map((x) => x.id), ['c']);
    expect([taskIdle(list[0]), taskIdle(list[1])], [isFalse, isTrue]);
    expect(taskSummary(list), '3 个任务 · 1 个在跑 · 1 个需要留意');
  });

  testWidgets('列表行：问题字警示色 + 计划', (tester) async {
    await pump(tester, FakeApi(tasks: [paused()], runs: const []), '/me/tasks');
    expect(find.text('需要留意'), findsOneWidget);
    final rich = find.byWidgetPredicate((w) => w is RichText && w.text.toPlainText() == '连续失败 3 次，已暂停 · 每天 08:00');
    expect(rich, findsOneWidget);
  });

  testWidgets('详情页：说明条，打开开关后收起', (tester) async {
    final api = PatchApi(tasks: [paused()], runs: [runJson('r1', 'error', error: '模型调用失败：401')]);
    await pump(tester, api, '/me/tasks/t1');
    expect(find.textContaining('连着失败了 3 次'), findsOneWidget);
    expect(find.text('连续失败，已暂停'), findsOneWidget);
    await tester.tap(find.byType(Switch));
    await tester.pumpAndSettle();
    expect(api.calls.any((c) => c.startsWith('PATCH /api/tasks/t1')), isTrue);
    expect(find.textContaining('连着失败了 3 次'), findsNothing);
  });
}
