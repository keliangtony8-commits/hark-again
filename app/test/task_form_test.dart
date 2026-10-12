// 任务表单（task_form.dart，新建/编辑/面板共用）：编辑只发改了的字段（名称、指令），什么都没改不发请求；
// 面板的表单叫“编辑面板”、字段叫“标题”，没有“重复/一次”切换（面板只能按 cron 重复）。
// 模型 / 思考（task_model_picker.dart）：服务器给了可选列表才出现；选深度 → 思考一行淡入，选“高”只发这两项；
// 详情页写“深度 · 思考 高”；换回快速（不能调）→ 两项都清回默认（null）；只有一个不能调的模型 → 整块不出现。
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'task_runs_test.dart' show FakeApi, pump, runJson, taskJson;

const _catalog = {
  'default': 'fast',
  'models': [
    {'id': 'fast', 'label': '快速'},
    {
      'id': 'smart',
      'label': '深度',
      'effort': 'medium',
      'efforts': [
        {'id': 'low', 'label': '低', 'description': '想得少'},
        {'id': 'medium', 'label': '中', 'description': '兼顾'},
        {'id': 'high', 'label': '高', 'description': '想得深'},
      ],
    },
  ],
};

class _Api extends FakeApi {
  _Api({required super.tasks, required super.runs, this.catalog});
  final patched = <Map<String, dynamic>>[];
  final Map<String, dynamic>? catalog;

  @override
  Future<dynamic> get(String path) async {
    if (path == '/api/catalog/models' && catalog != null) return catalog;
    return super.get(path);
  }

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

  testWidgets('模型 / 思考：选深度 + 高只发这两项，换回快速清回默认', (tester) async {
    final api = _Api(tasks: [taskJson(last: 'ok')], runs: [], catalog: _catalog);
    await _openEdit(tester, api);
    expect(find.byKey(const Key('task-model-fast')), findsOneWidget);
    expect(find.byKey(const Key('task-effort-high')), findsNothing); // 快速不能调：没有思考一行
    await tester.tap(find.byKey(const Key('task-model-smart')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('task-effort-high')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('保存'));
    await tester.pumpAndSettle();
    expect(api.patched.single, {'model': 'smart', 'reasoning': 'high'});
    expect(find.text('结果放进 Home 收件箱 · 深度 · 思考 高'), findsOneWidget);

    await tester.tap(find.byTooltip('编辑'));
    await tester.pumpAndSettle();
    expect(tester.widget<ChoiceChip>(find.byKey(const Key('task-effort-high'))).selected, isTrue);
    await tester.tap(find.byKey(const Key('task-model-fast')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('task-effort-high')), findsNothing);
    await tester.tap(find.text('保存'));
    await tester.pumpAndSettle();
    expect(api.patched.last, {'model': null, 'reasoning': null});
    expect(find.text('结果放进 Home 收件箱'), findsOneWidget);
  });

  testWidgets('只有一个不能调的模型：不出现', (tester) async {
    final api = _Api(tasks: [taskJson(last: 'ok')], runs: [], catalog: const {
      'default': 'fast',
      'models': [
        {'id': 'fast', 'label': '快速'},
      ],
    });
    await _openEdit(tester, api);
    expect(find.text('模型'), findsNothing);
    expect(find.text('思考'), findsNothing);
  });
}
