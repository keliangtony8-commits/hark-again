// 子助手卡（v1.48）：纯规则（进度词、副标题、能否展开、读屏）+ 卡片行为——解析、在做的脉冲只在 live 时、
// 完成后点开看结论、没成显示原因、空卡不画、独立成卡。
import 'package:assistant/blocks/block_view.dart';
import 'package:assistant/models/block.dart';
import 'package:assistant/models/delegate.dart';
import 'package:assistant/theme/app_theme.dart';
import 'package:assistant/ui/motion.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

DelegateBlock _d(List<Map<String, dynamic>> tasks, {bool live = false}) =>
    Block.fromJson({'type': 'delegate', 'tasks': tasks, 'live': live}) as DelegateBlock;

Future<void> _show(WidgetTester t, DelegateBlock b) => t.pumpWidget(MaterialApp(
      theme: buildTheme(Brightness.light),
      home: Scaffold(body: Padding(padding: const EdgeInsets.all(16), child: BlockView(b))),
    ));

void main() {
  test('规则：解析、进度、副标题、展开、读屏', () {
    final b = _d([
      {'title': '查价格', 'state': 'running', 'steps': 3, 'now': '正在搜索'},
      {'title': '看评论', 'state': 'done', 'steps': 7, 'seconds': 42, 'result': '好评多'},
      {'title': '怪', 'state': 'weird'},
    ], live: true);
    expect(b.live, isTrue);
    expect(b.tasks.map((t) => t.state), [DelegateState.running, DelegateState.done, DelegateState.running]);
    expect(delegateProgress(b), '已完成 1/3');
    expect(delegateTaskLine(b.tasks[0]), '第 3 步 · 正在搜索');
    expect(delegateTaskLine(b.tasks[1]), '7 步 · 42 秒');
    expect(delegateTaskLine(b.tasks[2]), '刚开始');
    expect(delegateTaskLine(const DelegateTask('x', DelegateState.running, steps: 2)), '第 2 步 · 在想');
    expect(delegateTaskLine(const DelegateTask('x', DelegateState.failed, note: '出错：502')), '出错：502');
    expect(delegateTaskLine(const DelegateTask('x', DelegateState.partial)), '部分完成');
    expect(delegateTaskLine(const DelegateTask('x', DelegateState.stopped)), '本轮已停止');
    expect(delegateHasResult(b.tasks[1]), isTrue);
    expect(delegateHasResult(b.tasks[0]), isFalse);
    expect(delegateProgress(_d([{'title': 'a', 'state': 'done'}, {'title': 'b', 'state': 'done'}])), '2 项全部完成');
    expect(delegateProgress(_d([{'title': 'a', 'state': 'done'}, {'title': 'b', 'state': 'failed'}])), '已完成 1/2');
    expect(delegateSemantics(_d([{'title': 'a', 'state': 'done', 'steps': 1}])), '子助手，1 项全部完成；a，已完成，1 步');
    expect(standsAlone(b), isTrue);
    expect((Block.fromJson({'type': 'delegate'}) as DelegateBlock).tasks, isEmpty);
  });

  testWidgets('在做：脉冲只在 live；结束后换成状态图标', (t) async {
    await _show(t, _d([{'title': '查价格', 'state': 'running', 'steps': 1, 'now': '正在搜索'}], live: true));
    await t.pump(const Duration(milliseconds: 500));
    expect(find.text('子助手'), findsOneWidget);
    expect(find.text('第 1 步 · 正在搜索'), findsOneWidget);
    expect(find.byType(PulseDot), findsOneWidget);
    await _show(t, _d([{'title': '查价格', 'state': 'failed', 'steps': 1, 'note': '出错：502'}]));
    await t.pumpAndSettle();
    expect(find.byType(PulseDot), findsNothing);
    expect(find.byIcon(Icons.error_outline_rounded), findsOneWidget);
    expect(find.text('出错：502'), findsOneWidget);
    expect(find.byIcon(Icons.expand_more_rounded), findsNothing); // 没结论：不能展开
  });

  testWidgets('完成后点开看交回的结论，再点收起', (t) async {
    await _show(t, _d([{'title': '看评论', 'state': 'done', 'steps': 7, 'seconds': 42, 'result': '好评多，差评集中在续航'}]));
    await t.pumpAndSettle();
    expect(find.text('好评多，差评集中在续航'), findsNothing);
    await t.tap(find.text('看评论'));
    await t.pumpAndSettle();
    expect(find.text('好评多，差评集中在续航'), findsOneWidget);
    await t.tap(find.text('看评论'));
    await t.pumpAndSettle();
    expect(find.text('好评多，差评集中在续航'), findsNothing);
  });

  testWidgets('空卡不画', (t) async {
    await _show(t, _d([]));
    expect(find.text('子助手'), findsNothing);
  });
}
