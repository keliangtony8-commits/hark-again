// v1.28 活动时间线：规则（文案/计时/合并/老服务器退化）+ 回复上方“用了 N 步”行、展开逐步、读屏、没成的步骤。
import 'package:assistant/features/chat/activity_view.dart';
import 'package:assistant/features/chat/message_view.dart';
import 'package:assistant/models/activity.dart';
import 'package:assistant/models/block.dart';
import 'package:assistant/models/message.dart';
import 'package:assistant/theme/app_theme.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

Map<String, dynamic> _step(String id, String title, String detail, String state, String at, int? ms, [String note = '']) =>
    {'id': id, 'tool': 'run_command', 'title': title, 'detail': detail, 'state': state, 'at': at, 'ms': ?ms, if (note.isNotEmpty) 'note': note};

final _json = {
  'id': 'm1',
  'role': 'assistant',
  'blocks': [
    {'type': 'text', 'text': '整理好了。'}
  ],
  'steps': [
    _step('a', '运行命令', 'ls -la', 'done', '2026-10-12T05:00:00+00:00', 400),
    _step('b', '写文件', 'notes/a.md', 'done', '2026-10-12T05:00:02+00:00', 120),
    _step('c', '运行命令', 'false', 'error', '2026-10-12T05:00:05+00:00', 7000, '退出码 1'),
  ],
};

Widget _host(Message m) => ProviderScope(
      child: MaterialApp(
        theme: buildTheme(Brightness.light),
        home: Scaffold(body: SingleChildScrollView(child: SizedBox(width: 400, child: MessageView(m)))),
      ),
    );

void main() {
  test('规则：解析、整段用时、摘要、合并、老服务器 tool.status', () {
    final m = Message.fromJson(_json);
    expect(m.steps.length, 3);
    expect(m.steps[2].state, ActivityState.error);
    expect(m.steps[2].failed, isTrue);
    expect(activitySpanMs(m.steps), 12000); // 05:00:00 → 05:00:05 + 7 秒
    expect(activitySummary(m.steps), '用了 3 步 · 12 秒');
    expect(activitySummary(m.steps.take(2).toList(), pending: true), '已用 2 步');
    expect(failedSteps(m.steps), 1);
    expect(stepDuration(400), '0.4 秒');
    expect(stepDuration(65000), '1 分 5 秒');
    expect(stepSemantics(m.steps[2]), '运行命令 false，没成功，退出码 1，用时 7 秒');
    final old = ActivityStep.fromStatus({'id': 'x', 'name': 'web_search', 'label': '正在搜索', 'state': 'running'});
    expect((old.title, old.running), ('搜索', true));
    var list = mergeStep(const [], old);
    list = mergeStep(list, ActivityStep.fromStatus({'id': 'x', 'state': 'done', 'step': _step('x', '搜索', '天气', 'done', '2026-10-12T05:00:00+00:00', 900)}));
    expect(list.single.detail, '天气');
    expect(list.single.running, isFalse);
    expect(activitySummary([const ActivityStep(id: 'z', title: '搜索', state: ActivityState.done)]), '用了 1 步'); // 没时间不报用时
    expect(Message.fromJson({'id': 'u', 'role': 'user', 'blocks': []}).steps, isEmpty);
  });

  testWidgets('回复上方一行“用了 3 步 · 12 秒 · 1 步没成”，点开逐步回看', (tester) async {
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    await tester.pumpWidget(_host(Message.fromJson(_json)));
    await tester.pumpAndSettle();
    expect(find.text('用了 3 步 · 12 秒'), findsOneWidget);
    expect(find.text('1 步没成'), findsOneWidget);
    expect(find.byType(StepRow), findsNothing);
    final row = find.text('用了 3 步 · 12 秒');
    expect(tester.getTopLeft(row).dy, lessThan(tester.getTopLeft(find.text('整理好了。')).dy)); // 在回复上方
    await tester.tap(row);
    await tester.pumpAndSettle();
    expect(find.byType(StepRow), findsNWidgets(3));
    expect(find.text('ls -la'), findsOneWidget);
    expect(find.text('退出码 1'), findsOneWidget);
    expect(find.text('0.4 秒'), findsOneWidget);
    expect(find.bySemanticsLabel('运行命令 ls -la，完成，用时 0.4 秒'), findsOneWidget);
    await tester.tap(row);
    await tester.pumpAndSettle();
    expect(find.byType(StepRow), findsNothing);
  });

  testWidgets('没用工具的回复没有这一行；生成中：正在跑的步骤是小条，有完成的步骤才出“已用 N 步”', (tester) async {
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    await tester.pumpWidget(_host(const Message(id: 'p', role: 'assistant', blocks: [TextBlock('你好')])));
    await tester.pumpAndSettle();
    expect(find.byType(ActivitySummary), findsNothing);

    const running = ActivityStep(id: 'r', title: '运行命令', detail: 'pip install a');
    await tester.pumpWidget(_host(const Message(id: 'pending', role: 'assistant', pending: true, blocks: [], steps: [running])));
    await tester.pump(const Duration(milliseconds: 500));
    expect(find.byType(ActivitySummary), findsNothing);
    expect(find.text('正在运行命令'), findsOneWidget);
    expect(find.text(' · pip install a'), findsOneWidget);

    const done = ActivityStep(id: 'd', title: '读文件', detail: 'a.txt', state: ActivityState.done, ms: 30);
    await tester.pumpWidget(_host(const Message(id: 'pending', role: 'assistant', pending: true, blocks: [], steps: [done, running])));
    await tester.pump(const Duration(milliseconds: 500));
    expect(find.text('已用 2 步'), findsOneWidget);
  });
}
