// v0.53：底部弹层统一玻璃化（GlassSheet）+ 输入框坐在玻璃上（tile 底、聚焦变实底）+ 架构守卫。
import 'dart:io';

import 'package:assistant/theme/app_theme.dart';
import 'package:assistant/theme/tokens.dart';
import 'package:assistant/ui/glass.dart';
import 'package:assistant/ui/sheets.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

Widget _app(void Function(BuildContext) open, {bool solid = false}) => MaterialApp(
      theme: buildTheme(Brightness.light),
      builder: (_, c) => GlassMode(solid: solid, child: c!),
      home: Builder(builder: (context) => Scaffold(body: Center(child: TextButton(onPressed: () => open(context), child: const Text('打开'))))),
    );

DecoratedBox _sheetBox(WidgetTester tester) => tester.widget<DecoratedBox>(
      find.descendant(of: find.byType(GlassSheet), matching: find.byType(DecoratedBox)).first,
    );

void main() {
  testWidgets('表单弹层：玻璃框（真模糊 + glassSheet 着色 + 把手），输入框 tile 底、聚焦变实底', (tester) async {
    await tester.pumpWidget(_app((c) => showFormSheet(c, title: '新建', fields: const [FieldSpec('name', '名字')])));
    await tester.tap(find.text('打开'));
    await tester.pumpAndSettle();
    expect(find.byType(GlassSheet), findsOneWidget);
    expect(find.descendant(of: find.byType(GlassSheet), matching: find.byType(BackdropFilter)), findsOneWidget);
    expect(find.byKey(const ValueKey('sheet-grabber')), findsOneWidget);
    expect((_sheetBox(tester).decoration as BoxDecoration).color, Palette.light.glassSheet);

    // 第一项自动聚焦 → 实底；收起焦点 → tile 底
    Color fill() {
      final deco = tester.widget<InputDecorator>(find.byType(InputDecorator)).decoration;
      final theme = Theme.of(tester.element(find.byType(InputDecorator))).inputDecorationTheme;
      final c = deco.fillColor ?? theme.fillColor!;
      final focused = tester.widget<InputDecorator>(find.byType(InputDecorator)).isFocused;
      return WidgetStateProperty.resolveAs<Color>(c, {if (focused) WidgetState.focused});
    }

    expect(fill(), Palette.light.surface);
    FocusManager.instance.primaryFocus?.unfocus();
    await tester.pumpAndSettle();
    expect(fill(), Palette.light.tile);
  });

  testWidgets('减少透明度：弹层实色、不模糊', (tester) async {
    await tester.pumpWidget(_app(
      (c) => showActionSheet<int>(c, title: '操作', actions: const [SheetAction(Icons.edit, '改名', value: 1)]),
      solid: true,
    ));
    await tester.tap(find.text('打开'));
    await tester.pumpAndSettle();
    expect(find.byType(GlassSheet), findsOneWidget);
    expect(find.descendant(of: find.byType(GlassSheet), matching: find.byType(BackdropFilter)), findsNothing);
    expect((_sheetBox(tester).decoration as BoxDecoration).color, Palette.light.surface);
    await tester.tap(find.text('改名'));
    await tester.pumpAndSettle();
    expect(find.byType(GlassSheet), findsNothing);
  });

  testWidgets('长列表弹层：短内容就是短弹层，长内容封顶在 85% 屏高并在里面滚', (tester) async {
    Future<void> open(int n) async {
      await tester.pumpWidget(_app((c) => showAppScrollSheet<void>(c, builder: (_) => Column(mainAxisSize: MainAxisSize.min, children: [
            const Text('标题'),
            SheetList(children: [for (var i = 0; i < n; i++) ListTile(title: Text('行 $i'))]),
          ]))));
      await tester.tap(find.text('打开'));
      await tester.pumpAndSettle();
    }

    final screen = tester.view.physicalSize.height / tester.view.devicePixelRatio;
    await open(3);
    final short = tester.getSize(find.byType(GlassSheet)).height;
    expect(short, lessThan(screen * 0.5)); // 不再固定开到 60%，下面不空一大片
    expect(find.text('行 2'), findsOneWidget);
    Navigator.of(tester.element(find.byType(GlassSheet))).pop();
    await tester.pumpAndSettle();

    await open(60);
    final tall = tester.getSize(find.byType(GlassSheet)).height;
    expect(tall, lessThanOrEqualTo(screen * 0.85 + 0.5));
    expect(tall, greaterThan(screen * 0.8));
    expect(find.text('行 0'), findsOneWidget);
    await tester.drag(find.byType(ListView), const Offset(0, -600));
    await tester.pumpAndSettle();
    expect(find.text('行 0'), findsNothing); // 封顶后在里面滚
  });

  testWidgets('危险确认：玻璃对话框（真模糊 + 磨砂遮罩），两颗等宽胶囊，动作是实心危险色', (tester) async {
    bool? result;
    await tester.pumpWidget(_app((c) async => result = await confirmDanger(c, title: '删除记忆？', text: '删了就找不回来了')));
    await tester.tap(find.text('打开'));
    await tester.pumpAndSettle();
    expect(find.byType(GlassDialog), findsOneWidget);
    expect(find.byType(AlertDialog), findsNothing);
    expect(find.descendant(of: find.byType(GlassDialog), matching: find.byType(BackdropFilter)), findsOneWidget);
    expect(find.byType(BackdropFilter), findsNWidgets(2)); // 框自己 + 整页磨砂
    final pills = tester.widgetList<PillButton>(find.byType(PillButton)).toList();
    expect(pills.map((b) => b.label), ['取消', '删除']);
    expect(pills.last.danger, isTrue);
    expect(tester.getSize(find.byType(PillButton).first).width, tester.getSize(find.byType(PillButton).last).width);
    await tester.tap(find.text('删除'));
    await tester.pumpAndSettle();
    expect(result, isTrue);
    expect(find.byType(GlassDialog), findsNothing);

    // 点遮罩 = 取消
    await tester.tap(find.text('打开'));
    await tester.pumpAndSettle();
    await tester.tapAt(const Offset(5, 5));
    await tester.pumpAndSettle();
    expect(result, isFalse);
  });

  testWidgets('对话框在减少透明度下实色、不模糊；减少动态下直接到位', (tester) async {
    await tester.pumpWidget(MediaQuery(
      data: const MediaQueryData(disableAnimations: true),
      child: _app((c) => confirmDanger(c, title: '确定？'), solid: true),
    ));
    await tester.tap(find.text('打开'));
    await tester.pump(); // 一帧就到位，不需要 settle
    expect(find.byType(GlassDialog), findsOneWidget);
    expect(find.byType(BackdropFilter), findsNothing);
    final box = tester.widget<DecoratedBox>(find.descendant(of: find.byType(GlassDialog), matching: find.byType(DecoratedBox)).at(1));
    expect((box.decoration as BoxDecoration).color, Palette.light.surface);
  });

  testWidgets('GlassFills：卡片 半透明 card ↔ 实色 surface（v3.5.1），小块/发丝线 玻璃 ↔ 实色', (tester) async {
    late Color card, tile, line;
    Widget probe(bool solid) => GlassMode(
          solid: solid,
          child: MaterialApp(
            theme: buildTheme(Brightness.light),
            home: Builder(builder: (c) {
              card = c.cardFill;
              tile = c.tileFill;
              line = c.hairline;
              return const SizedBox();
            }),
          ),
        );
    await tester.pumpWidget(probe(false));
    expect([card, tile, line], [Palette.light.card, Palette.light.tile, Palette.light.glassBorder]);
    await tester.pumpWidget(probe(true));
    expect([card, tile, line], [Palette.light.surface, Palette.light.surface2, Palette.light.border]);
  });

  test('架构守卫：弹层/对话框只经 ui/sheets.dart，AppBar 只在 ui/sub_page.dart，全 App 不写死 surface2、不手写投影', () {
    final offenders = <String>[];
    for (final f in Directory('lib').listSync(recursive: true).whereType<File>().where((f) => f.path.endsWith('.dart'))) {
      final path = f.path.replaceAll('\\', '/');
      final code = f.readAsLinesSync().where((l) => !l.trimLeft().startsWith('//')).join('\n');
      if (!path.endsWith('ui/sheets.dart') && RegExp(r'\bshowModalBottomSheet\b|\bshowBottomSheet\b').hasMatch(code)) offenders.add('$path: 弹层');
      if (!path.endsWith('ui/sheets.dart') && RegExp(r'\bshow(General)?Dialog\b|\bshowMenu\b|\bPopupMenuButton\b|\bAlertDialog\b').hasMatch(code)) {
        offenders.add('$path: 对话框/弹出菜单');
      }
      // 坐在 AI 玻璃卡里的东西只用 context.tileFill / cardFill，不写死实色 surface/surface2
      // v0.58 起全 App：surface2 只在 theme/ 和 ui/glass_mode.dart（GlassFills 的实色分支）出现，其余一律 context.tileFill
      final fillsHome = path.contains('lib/theme/') || path.endsWith('ui/glass_mode.dart');
      if (!fillsHome && RegExp(r'\bsurface2\b').hasMatch(code)) offenders.add('$path: surface2');
      // 外投影只走 glass.dart 的 floatShadow（浮层）；页面不手写 boxShadow / elevation
      if (!path.endsWith('ui/glass.dart') && RegExp(r'\bboxShadow\s*:|\belevation:\s*[1-9]').hasMatch(code)) offenders.add('$path: 手写投影');
      if (!path.endsWith('ui/sub_page.dart') && RegExp(r'(?<![A-Za-z])AppBar\(').hasMatch(code)) offenders.add('$path: AppBar');
    }
    expect(offenders, isEmpty);
  });
}
