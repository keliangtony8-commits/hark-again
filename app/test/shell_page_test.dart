// 一级页面外框：滚上去的内容在顶栏/标题那几行要渐隐，不能和标题叠字（v0.80 截图里“额度”压在消息上）。
// v3.3：渐隐不再是整页 ShaderMask(dstIn) 离屏层，而是顶部一条壁纸（BackdropFade）盖在内容上；毛玻璃按 glass.dart 的规则分组。
import 'package:assistant/shell/shell_page.dart';
import 'package:assistant/theme/app_theme.dart';
import 'package:assistant/theme/tokens.dart';
import 'package:assistant/ui/glass.dart';
import 'package:assistant/ui/sky.dart';
import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter_test/flutter_test.dart';

/// 按绘制顺序列出场景里每个毛玻璃层的 key（null = 不在任何组）。
List<BackdropKey?> _keys(WidgetTester tester) {
  final out = <BackdropKey?>[];
  void walk(Layer? l) {
    while (l != null) {
      if (l is BackdropFilterLayer) out.add(l.backdropKey);
      if (l is ContainerLayer) walk(l.firstChild);
      l = l.nextSibling;
    }
  }

  walk(tester.binding.renderViews.first.debugLayer);
  return out;
}

Widget _glass(String label) => GlassSurface(blur: true, child: SizedBox(width: 60, height: 40, child: Text(label)));

void main() {
  test('有标题行：标题底边以上全被壁纸盖住，让位线以下全显', () {
    const top = 24.0;
    final clear = BackdropFade.clearOf(top, Layout.chatTitle);
    final headerBottom = top + Layout.topBarTop + Layout.topBar + Sp.x2 + Layout.chatTitle;
    final inset = top + Layout.shellTop + Layout.chatTitle + Sp.x2;
    expect(clear, greaterThanOrEqualTo(headerBottom));
    expect(clear, lessThan(inset));
  });

  test('没有标题行：盖到顶栏中线，让位线以下全显', () {
    const top = 24.0;
    final clear = BackdropFade.clearOf(top, 0);
    expect(clear, greaterThan(top + Layout.topBarTop));
    expect(clear, lessThan(top + Layout.shellTop));
  });

  test('让位线下再缓入渐显一段（不切硬边），且不超过聊天列表顶部留白；渐隐条的 α 与原遮罩互补', () {
    const inset = 100.0;
    final solid = BackdropFade.solidOf(inset);
    expect(solid, inset + Layout.topFadeRamp);
    expect(Layout.topFadeRamp, lessThanOrEqualTo(Sp.x4));
    const clear = 60.0;
    expect(Sky.fadeAlpha(clear, clear, solid), 1); // clear 以上：全是壁纸 = 内容全透明
    expect(Sky.fadeAlpha(solid, clear, solid), 0); // solid 以下：没有壁纸 = 内容全显
    var last = 2.0;
    for (var k = 0; k <= 10; k++) {
      final a = Sky.fadeAlpha(clear + (solid - clear) * k / 10, clear, solid);
      expect(a, lessThan(last));
      last = a;
    }
    // 缓入：内容开头比线性更淡（壁纸 α 比线性更高）
    expect(1 - Sky.fadeAlpha(clear + (solid - clear) * 0.2, clear, solid), lessThan(0.2));
  });

  testWidgets('渐隐条只盖内容：画在内容之后、标题和左侧按钮之前；没有 ShaderMask 离屏层；不挡点击', (tester) async {
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    var taps = 0;
    await tester.pumpWidget(MaterialApp(
      theme: buildTheme(Brightness.light),
      home: ShellPage(
        headerHeight: Layout.chatTitle,
        header: const Text('标题'),
        lead: const Icon(Icons.notes_rounded),
        child: GestureDetector(onTap: () => taps++, child: const SizedBox.expand(child: Text('消息'))),
      ),
    ));
    expect(find.byType(ShaderMask), findsNothing);
    final fade = find.byType(BackdropFade);
    expect(fade, findsOneWidget);
    expect(find.descendant(of: fade, matching: find.byType(SkyLayer)), findsOneWidget);
    final f = tester.widget<BackdropFade>(fade);
    expect(f.clear, BackdropFade.clearOf(0, Layout.chatTitle));
    expect(tester.getRect(fade), Rect.fromLTWH(0, 0, tester.view.physicalSize.width, f.solid)); // 从屏幕顶到全显那一行

    // 绘制顺序 = 元素顺序：内容 → 渐隐条 → 左侧按钮 → 标题
    final order = <String>[];
    void visit(Element e) {
      final w = e.widget;
      if (w is Text && w.data == '消息') order.add('content');
      if (w is BackdropFade) order.add('fade');
      if (w is Icon) order.add('lead');
      if (w is Text && w.data == '标题') order.add('header');
      e.visitChildren(visit);
    }

    tester.binding.rootElement!.visitChildren(visit);
    expect(order, ['content', 'fade', 'lead', 'header']);

    await tester.tapAt(const Offset(400, 20)); // 渐隐条下面的内容照样能点（和原来被遮罩的内容一样）
    expect(taps, 1);
  });

  testWidgets('减少透明度：渐隐条是实色底，不画壁纸', (tester) async {
    await tester.pumpWidget(MaterialApp(
      theme: buildTheme(Brightness.dark),
      home: const GlassMode(solid: true, child: ShellPage(child: Text('消息'))),
    ));
    expect(find.byType(SkyLayer), findsNothing);
    expect(find.descendant(of: find.byType(BackdropFade), matching: find.byType(CustomPaint)), findsOneWidget);
  });

  testWidgets('毛玻璃分组：内容自成一组；左侧按钮与外层（顶栏）同组；盖层露出时左侧按钮另成一组', (tester) async {
    final covered = ValueNotifier(false);
    addTearDown(covered.dispose);
    await tester.pumpWidget(MaterialApp(
      theme: buildTheme(Brightness.light),
      home: BlurGroup(
        child: Stack(children: [
          ShellPage(
            covered: covered,
            lead: _glass('按钮'),
            child: Align(alignment: Alignment.bottomCenter, child: _glass('输入')),
          ),
          Align(alignment: Alignment.topCenter, child: _glass('顶栏')),
        ]),
      ),
    ));
    var k = _keys(tester);
    expect(k, hasLength(3)); // 绘制顺序：输入（内容）、按钮、顶栏
    expect(k.every((x) => x != null), isTrue);
    expect(k[0], isNot(k[1]));
    expect(k[1], k[2]);

    covered.value = true;
    await tester.pump();
    k = _keys(tester);
    expect(k[1], isNot(k[2]));
    expect(k[0], isNot(k[1]));

    covered.value = false;
    await tester.pump();
    k = _keys(tester);
    expect(k[1], k[2]);
  });

  testWidgets('路由转场中左侧按钮另成一组，转场结束回到外层组', (tester) async {
    final nav = GlobalKey<NavigatorState>();
    await tester.pumpWidget(MaterialApp(
      theme: buildTheme(Brightness.light),
      builder: (context, child) => BlurGroup(
        child: Stack(children: [child!, Align(alignment: Alignment.topCenter, child: _glass('顶栏'))]),
      ),
      navigatorKey: nav,
      home: ShellPage(lead: _glass('一'), child: const SizedBox.expand()),
    ));
    var k = _keys(tester);
    expect(k[0], k[1]);

    nav.currentState!.push(PageRouteBuilder<void>(
      transitionDuration: const Duration(milliseconds: 300),
      pageBuilder: (_, _, _) => ShellPage(lead: _glass('二'), child: const SizedBox.expand()),
      transitionsBuilder: (_, a, _, c) => FadeTransition(opacity: a, child: c),
    ));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 100));
    k = _keys(tester);
    final top = k.last;
    expect(k.sublist(0, k.length - 1).every((x) => x != top), isTrue, reason: '转场中两页的左侧按钮都不替顶栏取背景：$k');

    await tester.pumpAndSettle();
    k = _keys(tester);
    expect(k.first, k.last); // 第二页的按钮（第一页已被盖住不画）与顶栏同组
  });
}
