// 一次性任务（run_at）：解析、计划文案（一次 · 明天 08:00 / 已完成）、快捷时刻规则、TaskPlan 序列化，
// 新建表单切到“一次”发出 run_at + cron=''，详情页“编辑”切回重复（只发改了的字段）发出 cron + run_at=null。
import 'package:assistant/features/me/schedule_picker.dart';
import 'package:assistant/features/me/task_labels.dart';
import 'package:assistant/models/resources.dart';
import 'package:flutter/cupertino.dart' show CupertinoDatePicker;
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'task_runs_test.dart' show FakeApi, pump, runJson, taskJson;

Map<String, dynamic> onceJson(DateTime at, {bool done = false}) => {
      ...taskJson(last: done ? 'ok' : null),
      'name': '交作业',
      'cron': '',
      'run_at': at.toUtc().toIso8601String(),
      'next_run_at': done ? null : at.toUtc().toIso8601String(),
      'done': done,
    };

void main() {
  final now = DateTime(2026, 10, 11, 9, 30);

  test('解析与文案', () {
    final t = ScheduledTask.fromJson(onceJson(DateTime(2026, 10, 12, 8)));
    expect(t.isOnce, isTrue);
    expect(t.runAt!.toLocal(), DateTime(2026, 10, 12, 8));
    expect(scheduleLabel(t, now: now), '一次 · 明天 08:00');
    expect(nextRunLabel(t, now: now), ''); // 时刻已在计划里写了，不重复“下次”
    expect(taskIcon(t), Icons.alarm_rounded);
    final done = ScheduledTask.fromJson(onceJson(DateTime(2026, 10, 11, 8), done: true));
    expect([done.done, nextRunLabel(done, now: now), taskStateLabel(done, now: now)], [true, '已完成', '已完成']);
    final rep = ScheduledTask.fromJson(taskJson(last: 'ok'));
    expect([rep.isOnce, rep.done, scheduleLabel(rep)], [false, false, '每天 08:00']);
  });

  test('快捷时刻：今晚已过就不给，1 小时后取整到 5 分', () {
    final morning = onceShortcuts(now);
    expect(morning.map((e) => e.$1), ['1 小时后', '今晚 20:00', '明早 08:00', '明晚 20:00']);
    expect(morning.first.$2, DateTime(2026, 10, 11, 10, 35));
    expect(morning[2].$2, DateTime(2026, 10, 12, 8));
    final late = onceShortcuts(DateTime(2026, 10, 11, 19, 55));
    expect(late.map((e) => e.$1), isNot(contains('今晚 20:00')));
    expect(onceShortcuts(DateTime(2026, 10, 11, 23, 58)).first.$2, DateTime(2026, 10, 12, 1)); // 跨天进位
  });

  test('TaskPlan 序列化：两个字段都带，换模式时清掉另一个', () {
    final at = DateTime.utc(2026, 10, 12, 0);
    expect(const TaskPlan.repeat('0 8 * * *').toJson(), {'cron': '0 8 * * *', 'run_at': null});
    expect(TaskPlan.once(at).toJson(), {'cron': '', 'run_at': '2026-10-12T00:00:00.000Z'});
    expect(TaskPlan.of(ScheduledTask.fromJson(onceJson(at))).runAt, at.toLocal());
  });

  testWidgets('新建：切到“一次”→ 选时间出滚轮 → 发出 run_at', (tester) async {
    tester.view.devicePixelRatio = 1;
    tester.view.physicalSize = const Size(420, 900);
    addTearDown(tester.view.reset);
    final api = _Api(tasks: [], runs: []);
    await pump(tester, api, '/me/tasks');
    await tester.tap(find.byTooltip('新定时任务'));
    await tester.pumpAndSettle();
    await tester.enterText(find.byType(TextField).at(0), '带伞');
    await tester.enterText(find.byType(TextField).at(1), '提醒我：带伞');
    await tester.tap(find.text('一次'));
    await tester.pumpAndSettle();
    expect(find.text('明早 08:00'), findsOneWidget);
    expect(find.byType(CupertinoDatePicker), findsNothing);
    await tester.tap(find.byKey(const Key('plan-custom')));
    await tester.pumpAndSettle();
    expect(find.byType(CupertinoDatePicker), findsOneWidget);
    await tester.tap(find.text('明早 08:00'));
    await tester.pumpAndSettle();
    expect(find.byType(CupertinoDatePicker), findsNothing);
    await tester.tap(find.text('创建'));
    await tester.pumpAndSettle();
    final body = api.posted.single;
    expect(body['cron'], '');
    final at = DateTime.parse(body['run_at'] as String).toLocal();
    expect([at.hour, at.minute], [8, 0]);
    expect(find.textContaining('一次 · 明天 08:00'), findsOneWidget);
  });

  testWidgets('详情：编辑把一次换成重复', (tester) async {
    tester.view.devicePixelRatio = 1;
    tester.view.physicalSize = const Size(420, 900);
    addTearDown(tester.view.reset);
    final at = DateTime.now().add(const Duration(days: 1));
    final api = _Api(tasks: [onceJson(at)], runs: [runJson('r1', 'ok')]);
    await pump(tester, api, '/me/tasks/t1');
    expect(find.byIcon(Icons.alarm_rounded), findsOneWidget);
    await tester.tap(find.byTooltip('编辑'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('重复'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('工作日 09:00'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('保存'));
    await tester.pumpAndSettle();
    expect(api.patched.single, {'cron': '0 9 * * 1-5', 'run_at': null});
    expect(find.text('工作日 09:00'), findsOneWidget);
  });
}

class _Api extends FakeApi {
  _Api({required super.tasks, required super.runs});
  final posted = <Map<String, dynamic>>[];
  final patched = <Map<String, dynamic>>[];

  @override
  Future<dynamic> post(String path, [Object? body]) async {
    final b = (body as Map).cast<String, dynamic>();
    posted.add(b);
    final created = {...taskJson(last: null), 'id': 't2', ...b, 'next_run_at': b['run_at'], 'done': false};
    tasks = [created, ...tasks];
    return created;
  }

  @override
  Future<dynamic> patch(String path, Object body) async {
    final b = (body as Map).cast<String, dynamic>();
    patched.add(b);
    final updated = {...tasks.first, ...b, 'done': false};
    tasks = [updated];
    return updated;
  }
}
