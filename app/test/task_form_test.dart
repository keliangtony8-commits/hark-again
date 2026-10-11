// 任务表单（task_form.dart，新建/编辑/面板共用）：编辑只发改了的字段（名称、指令），什么都没改不发请求；
// 面板的表单叫“编辑面板”、字段叫“标题”，没有“重复/一次”切换（面板只能按 cron 重复）。
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'task_runs_test.dart' show FakeApi, pump, runJson, taskJson;

class _Api extends FakeApi {
  _Api({required super.tasks, required super.runs});
  final patched = <Map<String, dynamic>>[];

  @override
  Future<dynamic> patch(String path, Object body) async {
    final b = (body as Map).cast<String, dynamic>();
    patched.add(b);
    tasks = [
      {...tasks.first, ...b},
    ];
    return tasks.first;
  }
}

Future<void> _openEdit(WidgetTester tester, _Api api) async {
  tester.view.devicePixelRatio = 1;
  tester.view.physicalSize = const Size(420, 900);
  addTearDown(tester.view.reset);
  await pump(tester, api, '/me/tasks/t1');
  await tester.tap(find.byTooltip('编辑'));
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('编辑只发改了的字段', (tester) async {
    final api = _Api(tasks: [taskJson(last: 'ok')], runs: [runJson('r1', 'ok')]);
    await _openEdit(tester, api);
    expect(find.text('编辑任务'), findsOneWidget);
    expect(find.byKey(const Key('plan-mode')), findsOneWidget);
    await tester.enterText(find.byType(TextField).at(0), '早间新闻');
    await tester.enterText(find.byType(TextField).at(1), '总结今天的科技新闻');
    await tester.tap(find.text('保存'));
    await tester.pumpAndSettle();
    expect(api.patched.single, {'name': '早间新闻', 'prompt': '总结今天的科技新闻'});
    expect(find.text('早间新闻'), findsWidgets); // 标题栏跟着变
  });

  testWidgets('没改就不发请求', (tester) async {
    final api = _Api(tasks: [taskJson(last: 'ok')], runs: []);
    await _openEdit(tester, api);
    await tester.tap(find.text('保存'));
    await tester.pumpAndSettle();
    expect(api.patched, isEmpty);
  });

  testWidgets('面板：只能重复，改频率只发 cron', (tester) async {
    final api = _Api(tasks: [{...taskJson(last: 'ok'), 'output': 'panel', 'name': '天气'}], runs: []);
    await _openEdit(tester, api);
    expect(find.text('编辑面板'), findsOneWidget);
    expect(find.text('标题'), findsOneWidget);
    expect(find.byKey(const Key('plan-mode')), findsNothing);
    await tester.tap(find.text('工作日 09:00'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('保存'));
    await tester.pumpAndSettle();
    expect(api.patched.single, {'cron': '0 9 * * 1-5', 'run_at': null});
  });
}
