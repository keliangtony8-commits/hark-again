// 一级页面外框：滚上去的内容在顶栏/标题那几行要渐隐，不能和标题叠字（v0.80 截图里“额度”压在消息上）。
import 'package:assistant/shell/shell_page.dart';
import 'package:assistant/theme/app_theme.dart';
import 'package:assistant/theme/tokens.dart';
import 'package:assistant/ui/kit.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('有标题行：标题底边以上全透明，让位线以下全显', () {
    const top = 24.0;
    final clear = ShellPage.fadeClearOf(top, Layout.chatTitle);
    final headerBottom = top + Layout.topBarTop + Layout.topBar + Sp.x2 + Layout.chatTitle;
    final inset = top + Layout.shellTop + Layout.chatTitle + Sp.x2;
    expect(clear, greaterThanOrEqualTo(headerBottom));
    expect(clear, lessThan(inset));
  });

  test('没有标题行：透明到顶栏中线，让位线以下全显', () {
    const top = 24.0;
    final clear = ShellPage.fadeClearOf(top, 0);
    expect(clear, greaterThan(top + Layout.topBarTop));
    expect(clear, lessThan(top + Layout.shellTop));
  });

  test('让位线下再缓入渐显一段（不切硬边），且不超过聊天列表顶部留白', () {
    const inset = 100.0;
    expect(ShellPage.fadeSolidOf(inset), inset + Layout.topFadeRamp);
    expect(Layout.topFadeRamp, lessThanOrEqualTo(Sp.x4));
    expect(TopFade.alphaAt(0), 0);
    expect(TopFade.alphaAt(1), 1);
    var last = -1.0;
    for (final x in TopFade.ramp) {
      final a = TopFade.alphaAt(x);
      expect(a, greaterThan(last));
      last = a;
    }
    expect(TopFade.alphaAt(0.2), lessThan(0.2)); // 缓入：开头比线性更淡
  });

  testWidgets('只渐隐页面内容，标题和左侧按钮不受影响', (tester) async {
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    await tester.pumpWidget(MaterialApp(
      theme: buildTheme(Brightness.light),
      home: const ShellPage(
        headerHeight: Layout.chatTitle,
        header: Text('标题'),
        lead: Icon(Icons.notes_rounded),
        child: Text('消息'),
      ),
    ));
    expect(find.ancestor(of: find.text('消息'), matching: find.byType(TopFade)), findsOneWidget);
    expect(find.ancestor(of: find.text('标题'), matching: find.byType(TopFade)), findsNothing);
    expect(find.ancestor(of: find.byIcon(Icons.notes_rounded), matching: find.byType(TopFade)), findsNothing);
  });
}
