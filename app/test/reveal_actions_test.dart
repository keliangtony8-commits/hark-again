// 较早回复点一下露出操作行（v1.17）：最后一条常驻；更早的默认收着，点正文 / 卡片空白处切换；
// 同时只露一条由 ChatView 记（这里用小 harness 模拟）；没给 onReveal（生成中 / 最后一条）点了也不变。
import 'package:assistant/features/chat/message_view.dart';
import 'package:assistant/models/block.dart';
import 'package:assistant/models/message.dart';
import 'package:assistant/theme/app_theme.dart';
import 'package:assistant/ui/markdown.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

const _a = Message(id: 'a', role: 'assistant', blocks: [TextBlock('第一条回复：先看线代')]);
const _b = Message(id: 'b', role: 'assistant', blocks: [TextBlock('第二条回复：再刷真题')]);

/// 两条较早回复 + ChatView 同款的“同时只露一条”状态。
class _Harness extends StatefulWidget {
  const _Harness();
  @override
  State<_Harness> createState() => _HarnessState();
}

class _HarnessState extends State<_Harness> {
  String? revealed;
  @override
  Widget build(BuildContext context) => Column(children: [
        for (final m in [_a, _b])
          MessageView(m,
              key: ValueKey(m.id),
              revealed: revealed == m.id,
              onReveal: () => setState(() => revealed = revealed == m.id ? null : m.id),
              onSave: () {}),
      ]);
}

Future<void> _settle(WidgetTester tester) async {
  for (var i = 0; i < 10; i++) {
    await tester.pump(const Duration(milliseconds: 100));
  }
}

Future<void> _pump(WidgetTester tester, Widget child) async {
  tester.view.physicalSize = const Size(400, 800);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(ProviderScope(
    child: MaterialApp(theme: buildTheme(Brightness.light), home: Scaffold(body: child)),
  ));
  await _settle(tester);
}

void main() {
  testWidgets('最后一条常驻操作行', (tester) async {
    await _pump(tester, MessageView(_a, last: true, onSave: () {}));
    expect(find.byTooltip('复制'), findsOneWidget);
  });

  testWidgets('较早的回复点一下露出、再点收起；同时只露一条', (tester) async {
    await _pump(tester, const _Harness());
    expect(find.byTooltip('复制'), findsNothing);

    await tester.tap(find.textContaining('第一条回复'));
    await _settle(tester);
    expect(find.byTooltip('复制'), findsOneWidget);
    expect(find.byTooltip('存成文件'), findsOneWidget);
    expect(find.byTooltip('重新生成'), findsNothing); // 只有最后一条能重新生成

    // 点另一条：它露出，前一条收起
    await tester.tap(find.textContaining('第二条回复'));
    await _settle(tester);
    expect(find.byTooltip('复制'), findsOneWidget);
    final copyY = tester.getCenter(find.byTooltip('复制')).dy;
    expect(copyY, greaterThan(tester.getCenter(find.textContaining('第二条回复')).dy));

    await tester.tap(find.textContaining('第二条回复'));
    await _settle(tester);
    expect(find.byTooltip('复制'), findsNothing);
  });

  testWidgets('没给 onReveal 时点了不变（生成中 / 用户消息不进这里）', (tester) async {
    await _pump(tester, const MessageView(_a));
    await tester.tap(find.textContaining('第一条回复'));
    await _settle(tester);
    expect(find.byTooltip('复制'), findsNothing);
  });

  testWidgets('TextTapScope：可选中正文的点按传给外层', (tester) async {
    var taps = 0;
    await _pump(tester, TextTapScope(onTap: () => taps++, child: const AppMarkdown('点我一下')));
    await tester.tap(find.textContaining('点我一下'));
    await tester.pump();
    expect(taps, 1);
  });
}
