// 下次运行（服务端 next_run_at）：解析、文案规则（暂停/马上/明天/排队与失败优先）、
// 列表行与详情页都显示，停用后详情页立刻换成“已暂停”。
import 'package:assistant/features/me/task_labels.dart';
import 'package:assistant/models/resources.dart';
import 'package:assistant/ui/format.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'task_runs_test.dart' show FakeApi, pump, runJson, taskJson;

Map<String, dynamic> withNext(DateTime? at, {bool active = true, String? last = 'ok', bool requested = false}) =>
    {...taskJson(last: last, requested: requested), 'active': active, 'next_run_at': at?.toUtc().toIso8601String()};

void main() {
  final now = DateTime(2026, 10, 11, 9, 30);
  ScheduledTask t(DateTime? at, {bool active = true, String? last = 'ok', bool requested = false}) =>
      ScheduledTask.fromJson(withNext(at, active: active, last: last, requested: requested));

  test('解析与文案', () {
    expect(t(null).nextRunAt, isNull);
    expect(t(DateTime(2026, 10, 12, 8)).nextRunAt!.toLocal(), DateTime(2026, 10, 12, 8));
    expect(formatWhen(DateTime(2026, 10, 12, 8), now: now), '明天 08:00');
    expect(nextRunLabel(t(DateTime(2026, 10, 12, 8)), now: now), '下次 明天 08:00');
    expect(nextRunLabel(t(DateTime(2026, 10, 11, 21, 30)), now: now), '下次 今天 21:30');
    expect(nextRunLabel(t(now.add(const Duration(seconds: 20))), now: now), '马上运行');
    expect(nextRunLabel(t(now), now: now), '马上运行'); // 过期补跑：服务端给的就是“现在”
    expect(nextRunLabel(t(DateTime(2026, 10, 12, 8), active: false), now: now), '已暂停');
    expect(nextRunLabel(t(null), now: now), ''); // cron 无效
    expect(taskStateLabel(t(DateTime(2026, 10, 12, 8), last: 'error'), now: now), '上次失败');
    expect(taskStateLabel(t(DateTime(2026, 10, 12, 8), requested: true), now: now), '即将运行…');
    expect(taskStateLabel(t(DateTime(2026, 10, 12, 8)), now: now), '下次 明天 08:00');
  });

  testWidgets('列表行与详情页显示下次运行；停用后变“已暂停”', (tester) async {
    final at = DateTime.now().add(const Duration(days: 1));
    final api = _PatchApi(tasks: [withNext(at)], runs: [runJson('r1', 'ok')]);
    await pump(tester, api, '/me/tasks');
    final label = '下次 ${formatWhen(at)}';
    expect(find.textContaining(label), findsOneWidget);

    await tester.tap(find.text('每日新闻'));
    await tester.pumpAndSettle();
    expect(find.text(label), findsOneWidget);

    await tester.tap(find.byType(Switch).last);
    await tester.pumpAndSettle();
    expect(find.text('已暂停'), findsOneWidget);
    expect(find.text(label), findsNothing);
  });
}

/// PATCH 回服务端算好的新值（停用 → next_run_at=null）。
class _PatchApi extends FakeApi {
  _PatchApi({required super.tasks, required super.runs});

  @override
  Future<dynamic> patch(String path, Object body) async {
    final b = (body as Map).cast<String, dynamic>();
    final updated = {...tasks.first, ...b, if (b['active'] == false) 'next_run_at': null};
    tasks = [updated];
    return updated;
  }
}
