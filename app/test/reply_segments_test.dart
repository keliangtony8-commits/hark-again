// v0.84：回复按段排版——正文类块进回复卡（最宽 bubbleMax），卡片类块（审批/订单/表单/商品/摘要/浏览器）单独成卡、占满聊天区。
import 'package:assistant/blocks/block_frame.dart';
import 'package:assistant/features/chat/message_view.dart';
import 'package:assistant/models/activity.dart';
import 'package:assistant/models/block.dart';
import 'package:assistant/models/message.dart';
import 'package:assistant/theme/app_theme.dart';
import 'package:assistant/theme/tokens.dart';
import 'package:assistant/ui/glass.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

const _order = OrderBlock(id: 'o1', merchant: '店', items: [OrderLine(name: '耳机', price: '¥1')], total: '¥1');

Widget _host(Message m, {double width = 400}) => ProviderScope(
      child: MaterialApp(
        theme: buildTheme(Brightness.light),
        home: Scaffold(body: Align(alignment: Alignment.topLeft, child: SizedBox(width: width, child: MessageView(m)))),
      ),
    );

void main() {
  test('replySegments：连续正文合成一段，卡片块各自成段，未知块不切开正文', () {
    final s = replySegments(const [
      TextBlock('a'),
      CodeBlock(language: 'py', source: 'x'),
      _order,
      UnknownBlock('future'),
      TextBlock('b'),
      UnknownBlock('future'),
      TextBlock('c'),
      ApprovalBlock(id: 'a1', title: 't', detail: '', state: 'pending'),
    ]);
    expect([for (final x in s) x.card], [false, true, false, true]);
    expect(s[0].blocks.length, 2);
    expect(s[2].blocks.map((b) => (b as TextBlock).text), ['b', 'c']);
    expect(replySegments(const []), isEmpty);
    expect(standsAlone(const TextBlock('x')), false);
    expect(standsAlone(const SummaryBlock(title: 't', markdown: 'm')), true);
  });

  testWidgets('卡片块不在回复卡里、比回复卡宽；正文仍在玻璃回复卡里', (tester) async {
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    const m = Message(id: 'm1', role: 'assistant', blocks: [TextBlock('先看订单'), _order]);
    await tester.pumpWidget(_host(m));
    await tester.pumpAndSettle();
    final frame = find.byType(BlockFrame);
    expect(frame, findsOneWidget);
    expect(find.ancestor(of: frame, matching: find.byType(GlassSurface)), findsNothing);
    final bubble = find.ancestor(of: find.text('先看订单'), matching: find.byType(GlassSurface));
    expect(bubble, findsOneWidget);
    expect(tester.getSize(frame).width, 400);
    expect(tester.getSize(bubble).width, lessThanOrEqualTo(400 * Layout.bubbleMax));
  });

  testWidgets('平板宽度：卡片块封顶 chatCardMax', (tester) async {
    tester.view.devicePixelRatio = 1;
    tester.view.physicalSize = const Size(1200, 900);
    addTearDown(tester.view.reset);
    const m = Message(id: 'm1', role: 'assistant', blocks: [_order]);
    await tester.pumpWidget(_host(m, width: 1000));
    await tester.pumpAndSettle();
    expect(tester.getSize(find.byType(BlockFrame)).width, Layout.chatCardMax);
  });

  testWidgets('生成中最后一段是卡片：运行中的工具另起一张小回复卡', (tester) async {
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    const m = Message(
      id: 'p',
      role: 'assistant',
      pending: true,
      blocks: [_order],
      steps: [ActivityStep(id: 't1', title: '打开网页')],
    );
    await tester.pumpWidget(_host(m));
    await tester.pump(const Duration(milliseconds: 500));
    final chip = find.textContaining('打开网页');
    expect(chip, findsOneWidget);
    expect(find.ancestor(of: chip, matching: find.byType(GlassSurface)), findsOneWidget);
    expect(tester.getTopLeft(chip).dy, greaterThan(tester.getBottomLeft(find.byType(BlockFrame)).dy));
  });
}
