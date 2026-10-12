// 计划清单卡（v1.47）：纯规则（进度词、默认收起、读屏）+ 卡片行为——解析、标记随状态换、
// 进行中脉冲只在这一轮没结束时出现、做完结束自动收起并可点开、空清单不画、独立成卡。
import 'package:assistant/blocks/block_view.dart';
import 'package:assistant/blocks/plan_block.dart';
import 'package:assistant/models/block.dart';
import 'package:assistant/models/plan.dart';
import 'package:assistant/theme/app_theme.dart';
import 'package:assistant/ui/motion.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

PlanBlock _plan(List<List<String>> xs, {bool settled = false, String? why}) => Block.fromJson({
      'type': 'plan',
      'items': [for (final x in xs) {'content': x[0], 'status': x[1]}],
      'explanation': ?why,
      'settled': settled,
    }) as PlanBlock;

Future<void> _show(WidgetTester t, PlanBlock b) => t.pumpWidget(MaterialApp(
      theme: buildTheme(Brightness.light),
      home: Scaffold(body: Padding(padding: const EdgeInsets.all(16), child: BlockView(b))),
    ));

void main() {
  test('规则：解析、进度、收起、读屏', () {
    final b = _plan([['装依赖', 'completed'], ['写页面', 'in_progress'], ['跑起来', 'pending'], ['x', 'weird']]);
    expect(b.items.map((i) => i.status), [PlanStatus.completed, PlanStatus.inProgress, PlanStatus.pending, PlanStatus.pending]);
    expect(planDone(b), 1);
    expect(planProgress(b), '1/4');
    expect(planCurrent(b)?.content, '写页面');
    expect(planProgress(_plan([['a', 'completed'], ['b', 'pending']], settled: true)), '停在 1/2');
    final done = _plan([['a', 'completed'], ['b', 'completed']], settled: true);
    expect(planProgress(done), '2 步都完成了');
    expect(planCollapsedByDefault(done), isTrue);
    expect(planCollapsedByDefault(_plan([['a', 'completed']])), isFalse); // 还在这一轮里：展开
    expect(planSemantics(_plan([['a', 'pending']], why: '换方案')), '计划，0/1；调整原因：换方案；第1步 a，待做');
    expect(standsAlone(b), isTrue);
    expect((Block.fromJson({'type': 'plan'}) as PlanBlock).items, isEmpty);
  });

  testWidgets('进行中脉冲只在这一轮没结束时；结束后定格', (t) async {
    await _show(t, _plan([['装依赖', 'completed'], ['写页面', 'in_progress']], why: '改用 vite'));
    await t.pump(const Duration(milliseconds: 500));
    expect(find.text('计划'), findsOneWidget);
    expect(find.text('1/2'), findsOneWidget);
    expect(find.text('改用 vite'), findsOneWidget);
    expect(find.byType(PulseDot), findsOneWidget);
    expect(find.byIcon(Icons.check_circle_rounded), findsOneWidget);
    await _show(t, _plan([['装依赖', 'completed'], ['写页面', 'in_progress']], settled: true));
    await t.pumpAndSettle();
    expect(find.byType(PulseDot), findsNothing);
    expect(find.byIcon(Icons.adjust_rounded), findsOneWidget);
    expect(find.text('停在 1/2'), findsOneWidget);
  });

  testWidgets('看着做完：自动收起，点标题展开', (t) async {
    await _show(t, _plan([['a', 'completed'], ['b', 'in_progress']]));
    await t.pump(const Duration(milliseconds: 500));
    await _show(t, _plan([['a', 'completed'], ['b', 'completed']]));
    await t.pumpAndSettle();
    expect(find.text('b'), findsOneWidget); // 这一轮还没结束：展开
    await _show(t, _plan([['a', 'completed'], ['b', 'completed']], settled: true));
    await t.pumpAndSettle();
    expect(find.text('2 步都完成了'), findsOneWidget);
    expect(find.text('b'), findsNothing);
    await t.tap(find.text('计划'));
    await t.pumpAndSettle();
    expect(find.text('b'), findsOneWidget);
  });

  testWidgets('空清单不画；语义一整句', (t) async {
    await _show(t, _plan([]));
    expect(find.byType(PlanBlockView), findsOneWidget);
    expect(find.text('计划'), findsNothing);
    final h = t.ensureSemantics();
    await _show(t, _plan([['a', 'pending']]));
    await t.pumpAndSettle();
    expect(find.bySemanticsLabel('计划，0/1；第1步 a，待做'), findsOneWidget);
    h.dispose();
  });
}
