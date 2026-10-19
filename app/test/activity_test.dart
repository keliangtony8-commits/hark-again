// v1.28 活动时间线：规则（文案/计时/合并/老服务器退化）+ v3.5.5 步骤胶囊（回复下方一颗：生成中只显示当前一步、完成收成“N 个步骤”、点开逐步、读屏、没成的步骤）。
import 'package:assistant/features/chat/activity_view.dart';
import 'package:assistant/features/chat/message_view.dart';
import 'package:assistant/models/activity.dart';
import 'package:assistant/models/block.dart';
import 'package:assistant/models/message.dart';
import 'package:assistant/theme/app_theme.dart';
import 'package:assistant/ui/glass.dart';
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
    expect(activitySummary(m.steps), '3 个步骤 · 12 秒');
    // v3.5.5 生成中胶囊：最后一个进行中的步骤；两步之间（没有进行中的）= 正在思考
    expect(capsuleLabel(const [ActivityStep(id: 'a', title: '读文件', detail: 'a.txt', state: ActivityState.done), ActivityStep(id: 'b', title: '运行命令', detail: 'ls')]), ('正在运行命令', 'ls'));
    expect(capsuleLabel(const [ActivityStep(id: 'a', title: '读文件', state: ActivityState.done)]), ('正在思考', ''));
    expect(failedSteps(m.steps), 1);
    expect(stepDuration(400), isNull); // 不到 1 秒不写（10-14 16:01 满屏 0.0 秒）
    expect(stepDuration(3400), '3 秒');
    expect(stepDuration(65000), '1 分 5 秒');
    expect(stepSemantics(m.steps[2]), '运行命令 false，失败，退出码 1，用时 7 秒');
    final old = ActivityStep.fromStatus({'id': 'x', 'name': 'web_search', 'label': '正在搜索', 'state': 'running'});
    expect((old.title, old.running), ('搜索', true));
    var list = mergeStep(const [], old);
    list = mergeStep(list, ActivityStep.fromStatus({'id': 'x', 'state': 'done', 'step': _step('x', '搜索', '天气', 'done', '2026-10-12T05:00:00+00:00', 900)}));
    expect(list.single.detail, '天气');
    expect(list.single.running, isFalse);
    expect(activitySummary([const ActivityStep(id: 'z', title: '搜索', state: ActivityState.done)]), '1 个步骤'); // 没时间不报用时
    expect(Message.fromJson({'id': 'u', 'role': 'user', 'blocks': []}).steps, isEmpty);
  });

  testWidgets('完成后：回复下方胶囊“3 个步骤 · 12 秒 · 1 项失败”，点开逐步回看', (tester) async {
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    await tester.pumpWidget(_host(Message.fromJson(_json)));
    await tester.pumpAndSettle();
    expect(find.text('3 个步骤 · 12 秒'), findsOneWidget);
    expect(find.text('1 项失败'), findsOneWidget);
    expect(find.byType(StepRow), findsNWidgets(3)); // 停在出错的一步：自己展开（v2.79）
    final row = find.text('3 个步骤 · 12 秒');
    expect(tester.getTopLeft(row).dy, greaterThan(tester.getBottomLeft(find.text('整理好了。')).dy)); // 在回复下方（v3.5.5）
    expect(find.text('ls -la'), findsOneWidget);
    expect(find.text('退出码 1'), findsOneWidget);
    expect(find.textContaining('0.4'), findsNothing);
    expect(find.text('7 秒'), findsOneWidget);
    expect(find.bySemanticsLabel('运行命令 ls -la，已完成'), findsOneWidget);
    await tester.tap(row);
    await tester.pumpAndSettle();
    expect(find.byType(StepRow), findsNothing);
    await tester.tap(row);
    await tester.pumpAndSettle();
    expect(find.byType(StepRow), findsNWidgets(3));
  });

  test('自己展开：只有一轮停在出错的一步', () {
    const ok = ActivityStep(id: 'a', title: '运行命令', state: ActivityState.done);
    const bad = ActivityStep(id: 'b', title: '运行命令', state: ActivityState.error);
    const no = ActivityStep(id: 'c', title: '运行命令', state: ActivityState.denied);
    expect(activityOpensItself([bad, ok]), isFalse); // 换方法补救回来了
    expect(activityOpensItself([ok, bad]), isTrue);
    expect(activityOpensItself([ok, bad], pending: true), isFalse);
    expect(activityOpensItself([ok, no]), isFalse); // 没批准：批准卡已在回复里
    expect(activityOpensItself(const []), isFalse);
  });

  testWidgets('出错后补救回来了：默认收成一行', (tester) async {
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    final steps = [..._json['steps'] as List];
    await tester.pumpWidget(_host(Message.fromJson({..._json, 'steps': [steps[2], steps[0]]})));
    await tester.pumpAndSettle();
    expect(find.text('1 项失败'), findsOneWidget);
    expect(find.byType(StepRow), findsNothing);
  });

  testWidgets('没用工具的回复没有胶囊；生成中：只有一颗胶囊显示当前一步，换步骤原地替换，不逐条列出、不撑空卡', (tester) async {
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    await tester.pumpWidget(_host(const Message(id: 'p', role: 'assistant', blocks: [TextBlock('你好')])));
    await tester.pumpAndSettle();
    expect(find.byType(StepCapsule), findsNothing);

    const done = ActivityStep(id: 'd', title: '读文件', detail: 'a.txt', state: ActivityState.done, ms: 30);
    const running = ActivityStep(id: 'r', title: '运行命令', detail: 'pip install a');
    await tester.pumpWidget(_host(const Message(id: 'pending', role: 'assistant', pending: true, blocks: [], steps: [done, running])));
    await tester.pump(const Duration(milliseconds: 500));
    expect(find.byType(StepCapsule), findsOneWidget);
    expect(find.text('正在运行命令 · pip install a', findRichText: true), findsOneWidget);
    expect(find.textContaining('读文件', findRichText: true), findsNothing, reason: '已完成的步骤不逐条列出');
    expect(find.byType(GlassSurface), findsNothing, reason: '没出字时不撑空回复卡、也不出跳点');
    expect(find.byType(StepRow), findsNothing);

    // 步骤推进：同一颗胶囊原地换字
    const next = ActivityStep(id: 'n', title: '写文件', detail: 'b.txt');
    await tester.pumpWidget(_host(const Message(id: 'pending', role: 'assistant', pending: true, blocks: [], steps: [done, ActivityStep(id: 'r', title: '运行命令', state: ActivityState.done), next])));
    await tester.pumpAndSettle();
    expect(find.byType(StepCapsule), findsOneWidget);
    expect(find.text('正在写文件 · b.txt', findRichText: true), findsOneWidget);
    expect(find.textContaining('运行命令', findRichText: true), findsNothing);

    // 点胶囊：生成中也能看全部步骤
    await tester.tap(find.byType(StepCapsule));
    await tester.pumpAndSettle();
    expect(find.byType(StepRow), findsNWidgets(3));

    // 生成完：收成“3 个步骤”
    await tester.pumpWidget(_host(const Message(id: 'pending', role: 'assistant', blocks: [TextBlock('好了')], steps: [done, ActivityStep(id: 'r', title: '运行命令', state: ActivityState.done), ActivityStep(id: 'n', title: '写文件', state: ActivityState.done)])));
    await tester.pumpAndSettle();
    expect(find.text('3 个步骤', findRichText: true), findsOneWidget);
    expect(find.textContaining('正在', findRichText: true), findsNothing);
  });
}
