// v1.84 定时脚本（kind=script，到点直接在工作区跑命令、不调模型）：模型解析、文案（task_labels.dart）、
// 表单脚本模式（task_form.dart + notify_picker.dart：命令字段、什么时候告诉我、没有模型选择；新建发 kind/notify，编辑只发改了的）、
// 详情页（去向一行、命令等宽）、没开对话的运行点开看日志（showJobLog）。
import 'package:assistant/features/me/task_labels.dart';
import 'package:assistant/features/me/task_library.dart';
import 'package:assistant/models/resources.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'task_runs_test.dart' show FakeApi, pump, runJson, taskJson;

Map<String, dynamic> scriptJson({String notify = 'failure', String? project}) =>
    {...taskJson(last: 'ok'), 'name': '每晚备份', 'prompt': 'tar czf b.tgz notes', 'kind': 'script', 'notify': notify, 'project_id': project};

class _Api extends FakeApi {
  _Api({required super.tasks, required super.runs});
  final patched = <Map<String, dynamic>>[];
  final created = <Map<String, dynamic>>[];
  final logs = <String>[];

  @override
  Future<dynamic> get(String path) async {
    if (path.startsWith('/api/jobs/')) {
      logs.add(path);
      return {'id': 'j1', 'title': '每晚备份', 'command': 'tar', 'state': 'done', 'exit_code': 0, 'elapsed': 3, 'tail': 'backup ok'};
    }
    if (path == '/api/catalog/models') return {'default': 'fast', 'models': [{'id': 'fast', 'label': '快速'}, {'id': 'smart', 'label': '深度'}]};
    return super.get(path);
  }

  @override
  Future<dynamic> patch(String path, Object body) async {
    final b = (body as Map).cast<String, dynamic>();
    patched.add(b);
    tasks = [{...tasks.first, ...b}];
    return tasks.first;
  }

  @override
  Future<dynamic> post(String path, [Object? body]) async {
    if (path == '/api/tasks') {
      final b = (body as Map).cast<String, dynamic>();
      created.add(b);
      final row = {...taskJson(last: null), ...b, 'id': 't2'};
      tasks = [...tasks, row];
      return row;
    }
    return super.post(path, body);
  }
}

void _size(WidgetTester tester) {
  tester.view.devicePixelRatio = 1;
  tester.view.physicalSize = const Size(420, 900);
  addTearDown(tester.view.reset);
}

void main() {
  test('解析与文案', () {
    final t = ScheduledTask.fromJson(scriptJson(notify: 'change'));
    expect([t.isScript, t.notify, t.projectId], [true, 'change', null]);
    expect(taskIcon(t), Icons.terminal_rounded);
    expect(taskOutputLabel(t), '在我的文件中运行 · 输出变了告诉我');
    expect(taskOutputLabel(ScheduledTask.fromJson(scriptJson(project: 'p1'))), '在项目工作区中运行 · 失败时告诉我');
    final a = ScheduledTask.fromJson(taskJson());
    expect([a.isScript, a.kind, a.notify], [false, 'agent', 'failure']);
    expect(taskOutputLabel(a), '结果放进 Home 收件箱');
    expect(TaskRun.fromJson({...runJson('r', 'ok'), 'job_id': 'j1'}).jobId, 'j1');
    expect(scriptStarter.script, isTrue);
    expect(taskStarters, contains(scriptStarter));
  });

  testWidgets('新建定时脚本：命令 + 什么时候告诉我，没有模型选择，发 kind/notify', (tester) async {
    _size(tester);
    final api = _Api(tasks: [taskJson(last: 'ok')], runs: []);
    await pump(tester, api, '/me/tasks');
    await tester.tap(find.byTooltip('新定时脚本'));
    await tester.pumpAndSettle();
    expect(find.text('新定时脚本'), findsWidgets);
    expect(find.text('到点运行的命令'), findsOneWidget);
    expect(find.text('快速'), findsNothing); // 不调模型：没有模型选择
    expect(find.text('成功了不打扰；失败时结果进 Home 收件箱。'), findsOneWidget);
    await tester.enterText(find.byType(TextField).at(0), '抓价格');
    await tester.enterText(find.byType(TextField).at(1), 'python3 fetch.py');
    await tester.tap(find.byKey(const Key('notify-change')));
    await tester.pumpAndSettle();
    expect(find.textContaining('盯网页'), findsOneWidget);
    await tester.tap(find.text('创建'));
    await tester.pumpAndSettle();
    final b = api.created.single;
    expect([b['name'], b['prompt'], b['kind'], b['notify']], ['抓价格', 'python3 fetch.py', 'script', 'change']);
    expect(b.containsKey('model'), isFalse);
  });

  testWidgets('详情：去向一行、编辑脚本只发改了的 notify；没开对话的运行点开看日志', (tester) async {
    _size(tester);
    final api = _Api(tasks: [scriptJson()], runs: [{...runJson('r1', 'ok'), 'job_id': 'j1'}]);
    await pump(tester, api, '/me/tasks/t1');
    expect(find.text('在我的文件中运行 · 失败时告诉我'), findsOneWidget);
    expect(find.text('tar czf b.tgz notes'), findsOneWidget);
    await tester.tap(find.bySemanticsLabel(RegExp('点按看日志')));
    await tester.pumpAndSettle();
    expect(api.logs.first, '/api/jobs/j1');
    expect(find.text('backup ok'), findsOneWidget);
    await tester.tap(find.byTooltip('关闭')); // 全屏弹层：左上返回钮关掉（v3.5.1）
    await tester.pumpAndSettle();
    await tester.tap(find.byTooltip('编辑'));
    await tester.pumpAndSettle();
    expect(find.text('编辑脚本'), findsOneWidget);
    await tester.tap(find.byKey(const Key('notify-always')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('保存'));
    await tester.pumpAndSettle();
    expect(api.patched.single, {'notify': 'always'});
    expect(find.text('在我的文件中运行 · 每次都告诉我'), findsOneWidget);
  });
}
