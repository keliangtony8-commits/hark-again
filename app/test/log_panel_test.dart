// v2.55 记录面板（kind=log，服务端 app/panel_log.py；在聊天里说一句就记一笔，不调模型）：模型解析、文案（task_labels.dart）、
// 详情页（不显示模型、没有“跳过下一次”）、编辑只能改标题（task_form.dart，只发 name）。
import 'package:assistant/features/me/task_labels.dart';
import 'package:assistant/models/resources.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'task_runs_test.dart' show FakeApi, pump, taskJson;

Map<String, dynamic> logJson() => {
      ...taskJson(last: 'ok'),
      'name': '跑步',
      'prompt': '记录：跑步',
      'cron': '1 0 * * *',
      'output': 'panel',
      'kind': 'log',
      'next_run_at': DateTime.now().add(const Duration(hours: 5)).toUtc().toIso8601String(),
    };

class _Api extends FakeApi {
  _Api({required super.tasks, required super.runs});
  final patched = <Map<String, dynamic>>[];

  @override
  Future<dynamic> get(String path) async {
    if (path == '/api/catalog/models') return {'default': 'fast', 'models': [{'id': 'fast', 'label': '快速'}]};
    return super.get(path);
  }

  @override
  Future<dynamic> patch(String path, Object body) async {
    final b = (body as Map).cast<String, dynamic>();
    patched.add(b);
    tasks = [{...tasks.first, ...b}];
    return tasks.first;
  }
}

void main() {
  test('解析与文案', () {
    final t = ScheduledTask.fromJson(logJson());
    expect([t.isLog, t.isPanel, t.isScript, t.usesModel, t.canSkip], [true, true, false, false, false]);
    expect(taskIcon(t), Icons.edit_note_rounded);
    expect(scheduleLabel(t), '你说一句就记一笔');
    expect(nextRunLabel(t), '');
    expect(taskOutputLabel(t), '记录面板 · 不调用模型');
    final a = ScheduledTask.fromJson(taskJson());
    expect([a.isLog, a.usesModel], [false, true]);
  });

  testWidgets('详情：没有模型和跳过；编辑只改标题', (tester) async {
    tester.view.devicePixelRatio = 1;
    tester.view.physicalSize = const Size(420, 900);
    addTearDown(tester.view.reset);
    final api = _Api(tasks: [logJson()], runs: []);
    await pump(tester, api, '/me/tasks/t1');
    expect(find.text('记录面板 · 不调用模型'), findsOneWidget);
    expect(find.text('你说一句就记一笔'), findsOneWidget);
    expect(find.text('跳过下一次'), findsNothing);
    expect(find.textContaining('快速'), findsNothing);
    await tester.tap(find.byTooltip('编辑'));
    await tester.pumpAndSettle();
    expect(find.text('编辑面板'), findsOneWidget);
    expect(find.textContaining('说一句就记一笔（'), findsOneWidget);
    expect(find.byType(TextField), findsOneWidget); // 只有标题
    await tester.enterText(find.byType(TextField), '晨跑');
    await tester.tap(find.text('保存'));
    await tester.pumpAndSettle();
    expect(api.patched.single, {'name': '晨跑'});
  });
}
