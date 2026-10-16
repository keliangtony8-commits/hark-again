// v0.50：子页面统一外框 SubPage（壁纸 + 玻璃标题栏）、卡片/分组列表换成玻璃材质、下拉刷新让位。
import 'package:assistant/theme/app_theme.dart';
import 'package:assistant/theme/tokens.dart';
import 'package:assistant/ui/glass.dart';
import 'package:assistant/ui/kit.dart';
import 'package:assistant/ui/sub_page.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

Widget _app(Widget home, {bool solid = false}) => MaterialApp(
      theme: buildTheme(Brightness.light),
      builder: (_, c) => GlassMode(solid: solid, child: c!),
      home: home,
    );

double? _bodyTop;

Widget _page() => SubPage(
      title: const Text('记忆'),
      actions: [IconButton(onPressed: () {}, tooltip: '新增', icon: const Icon(Icons.add))],
      body: Builder(builder: (context) {
        _bodyTop = MediaQuery.paddingOf(context).top;
        return PullRefresh(
          onRefresh: () async {},
          child: const PageBody(children: [
            AppCard(child: Text('卡片')),
            ListGroup(children: [ListRow(icon: Icons.key, title: '一行'), ListRow(icon: Icons.key, title: '两行')]),
          ]),
        );
      }),
    );

void main() {
  testWidgets('子页面：壁纸 + Hark 式标题行（居中裸字 + 动作玻璃胶囊，v3.5 = 一级页顶栏位置），内容让出同一条让位线、从它下面滚过', (tester) async {
    await tester.pumpWidget(_app(_page()));
    await tester.pumpAndSettle();
    expect(find.byType(Backdrop), findsOneWidget);
    expect(find.byType(GlassAppBar), findsOneWidget);
    expect(find.descendant(of: find.byType(GlassAppBar), matching: find.byType(BackdropFilter)), findsOneWidget);
    expect(find.text('记忆'), findsOneWidget);
    expect(find.byTooltip('新增'), findsOneWidget);
    expect(_bodyTop, Layout.shellTop); // extendBodyBehindAppBar：让位线 = 一级页同一条（测试里状态栏为 0）
    // 胶囊：离顶 topBarTop、左右 gutter、高 topBar、全圆角玻璃面（和一级页顶栏同一个 GlassSurface）
    final w = tester.getSize(find.byType(Scaffold)).width;
    // 标题是裸字：没有玻璃底，按整屏宽居中
    expect(find.ancestor(of: find.text('记忆'), matching: find.byType(GlassSurface)), findsNothing);
    expect(tester.getCenter(find.text('记忆')).dx, moreOrLessEquals(w / 2, epsilon: 0.5));
    expect(tester.getCenter(find.text('记忆')).dy, moreOrLessEquals(Layout.topBarTop + Layout.topBar / 2, epsilon: 0.5));
    // 动作收进一颗玻璃胶囊，贴右边距、和顶栏同高
    final pill = find.ancestor(of: find.byTooltip('新增'), matching: find.byType(GlassSurface));
    final r = tester.getRect(pill);
    expect(r.right, w - Layout.gutter);
    expect(r.top, Layout.topBarTop);
    expect(r.height, Layout.topBar);
    expect(tester.widget<GlassSurface>(pill).radius, Radii.full);
    expect(find.byTooltip('返回'), findsNothing); // 首页路由退不了：不出返回钮（= AppBar 规则）

    final fade = tester.widget<BackdropFade>(find.byType(BackdropFade));
    expect(fade.clear, BackdropFade.clearOf(0, 0));
    expect(fade.solid, BackdropFade.solidOf(Layout.shellTop));
    final refresh = tester.widget<RefreshIndicator>(find.byType(RefreshIndicator));
    expect(refresh.edgeOffset, _bodyTop); // 转圈从标题栏下面出来
    expect(find.byType(ListGroup), findsOneWidget); // 分组只有 ListGroup 一种实现（v2.97 E1）
    // 第一张卡片在标题栏下面，而不是被它盖住
    expect(tester.getTopLeft(find.text('卡片')).dy, greaterThan(tester.getBottomLeft(find.byType(GlassAppBar)).dy));
  });

  testWidgets('能退的子页：左边一颗圆玻璃返回钮（= 顶栏圆钮位置和尺寸），点了退回', (tester) async {
    await tester.pumpWidget(_app(Builder(builder: (context) => Scaffold(body: Center(child: TextButton(onPressed: () => Navigator.of(context).push(MaterialPageRoute<void>(builder: (_) => _page())), child: const Text('进')))))));
    await tester.tap(find.text('进'));
    await tester.pumpAndSettle();
    final back = find.byTooltip('返回');
    expect(back, findsOneWidget);
    expect(find.descendant(of: find.byType(GlassAppBar), matching: find.byType(GlassIconButton)), findsOneWidget);
    expect(tester.getRect(find.descendant(of: find.byType(GlassIconButton), matching: find.byType(GlassSurface))), const Rect.fromLTWH(Layout.gutter, Layout.topBarTop, Layout.topBar, Layout.topBar));
    final w = tester.getSize(find.byType(GlassAppBar)).width;
    expect(tester.getCenter(find.text('记忆')).dx, moreOrLessEquals(w / 2, epsilon: 0.5)); // 有返回钮也按整屏居中
    await tester.tap(back);
    await tester.pumpAndSettle();
    expect(find.text('进'), findsOneWidget);
  });

  testWidgets('减少透明度：标题栏实色、不模糊；卡片用实色面', (tester) async {
    await tester.pumpWidget(_app(_page(), solid: true));
    await tester.pumpAndSettle();
    expect(find.byType(BackdropFilter), findsNothing);
    final ctx = tester.element(find.text('卡片'));
    final card = tester.widget<Container>(find.ancestor(of: find.text('卡片'), matching: find.byType(Container)).first);
    expect((card.decoration as BoxDecoration).color, ctx.palette.surface);
  });

  testWidgets('卡片是实色 surface（v2.80 F.2，和主页卡片同一材质）', (tester) async {
    await tester.pumpWidget(_app(_page()));
    await tester.pumpAndSettle();
    final ctx = tester.element(find.text('卡片'));
    final card = tester.widget<Container>(find.ancestor(of: find.text('卡片'), matching: find.byType(Container)).first);
    expect((card.decoration as BoxDecoration).color, ctx.palette.surface);
  });
}
