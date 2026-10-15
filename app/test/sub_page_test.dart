// v0.50：子页面统一外框 SubPage（壁纸 + 玻璃标题栏）、卡片/分组列表换成玻璃材质、下拉刷新让位。
import 'package:assistant/theme/app_theme.dart';
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
  testWidgets('子页面：壁纸 + 玻璃标题栏（模糊），内容让出标题栏高度、从它下面滚过', (tester) async {
    await tester.pumpWidget(_app(_page()));
    await tester.pumpAndSettle();
    expect(find.byType(Backdrop), findsOneWidget);
    expect(find.byType(GlassAppBar), findsOneWidget);
    expect(find.descendant(of: find.byType(GlassAppBar), matching: find.byType(BackdropFilter)), findsOneWidget);
    expect(find.text('记忆'), findsOneWidget);
    expect(find.byTooltip('新增'), findsOneWidget);
    expect(_bodyTop, greaterThanOrEqualTo(kToolbarHeight)); // extendBodyBehindAppBar：让位线 = 标题栏底
    final refresh = tester.widget<RefreshIndicator>(find.byType(RefreshIndicator));
    expect(refresh.edgeOffset, _bodyTop); // 转圈从标题栏下面出来
    expect(find.byType(ListGroup), findsOneWidget); // 分组只有 ListGroup 一种实现（v2.97 E1）
    // 第一张卡片在标题栏下面，而不是被它盖住
    expect(tester.getTopLeft(find.text('卡片')).dy, greaterThan(tester.getBottomLeft(find.byType(GlassAppBar)).dy));
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
