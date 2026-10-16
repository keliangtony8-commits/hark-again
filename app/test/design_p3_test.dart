// 设计 v2 P3：个性化偏好落盘、减少透明度、头像字色、关键数字块、项目活动字段、建议卡等宽胶囊、“我的”改头像色。
import 'package:assistant/blocks/block_view.dart';
import 'package:assistant/core/swr.dart';
import 'package:assistant/features/home/action_card.dart';
import 'package:assistant/features/me/avatar_color_sheet.dart';
import 'package:assistant/features/me/me_screen.dart';
import 'package:assistant/features/me/preferences_screen.dart';
import 'package:assistant/features/me/usage_screen.dart';
import 'package:assistant/models/usage.dart';
import 'package:assistant/models/block.dart';
import 'package:assistant/models/resources.dart';
import 'package:assistant/theme/app_theme.dart';
import 'package:assistant/theme/look.dart';
import 'package:assistant/theme/tokens.dart';
import 'package:assistant/ui/glass.dart';
import 'package:assistant/ui/kit.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'appearance_test.dart' show FlutterSecureStoragePlatformMock;

Widget _wrap(Widget child, {bool solid = false, Brightness b = Brightness.light}) => MaterialApp(
      theme: buildTheme(b),
      builder: (_, c) => GlassMode(solid: solid, child: c!),
      home: Scaffold(body: child),
    );

void main() {
  test('外观个性化：默认中性头像、不减透明；设置后落盘，清除头像色回到默认', () async {
    SharedPreferences.setMockInitialValues({});
    final c = ProviderContainer();
    addTearDown(c.dispose);
    final first = await c.read(lookProvider.future);
    expect(first.avatar, isNull);
    expect(first.solid, isFalse);
    await c.read(lookProvider.notifier).setAvatar(AvatarColors.presets[1]);
    await c.read(lookProvider.notifier).setSolid(true);
    final prefs = await SharedPreferences.getInstance();
    expect(prefs.getInt('look.avatar'), AvatarColors.presets[1].toARGB32());
    expect(prefs.getBool('look.solid'), isTrue);
    await c.read(lookProvider.notifier).setAvatar(null);
    expect(c.read(lookProvider).value!.avatar, isNull);
    expect(c.read(lookProvider).value!.solid, isTrue); // 改一项不动另一项
    expect(prefs.getInt('look.avatar'), isNull);
  });

  test('头像首字母按底色亮度选深/浅字；色环颜色饱和度明度固定', () {
    expect(AvatarColors.inkOn(const Color(0xFFF5F5F0)), AvatarColors.darkInk);
    expect(AvatarColors.inkOn(AvatarColors.presets[0]), AvatarColors.lightInk);
    final c = HSVColor.fromColor(wheelColor(200));
    expect(c.saturation, closeTo(AvatarColors.wheelSaturation, 0.01));
    expect(c.value, closeTo(AvatarColors.wheelValue, 0.01));
  });

  testWidgets('减少透明度：玻璃变实色、壁纸变纯色、没有任何 BackdropFilter', (tester) async {
    Widget page() => const Stack(children: [
          Positioned.fill(child: Backdrop()),
          Center(child: GlassSurface(blur: true, child: SizedBox(width: 100, height: 40))),
        ]);
    await tester.pumpWidget(_wrap(page()));
    await tester.pumpAndSettle();
    expect(find.byType(BackdropFilter), findsOneWidget);

    await tester.pumpWidget(_wrap(page(), solid: true));
    await tester.pumpAndSettle();
    expect(find.byType(BackdropFilter), findsNothing);
    final box = tester.widget<AnimatedContainer>(find.descendant(of: find.byType(GlassSurface), matching: find.byType(AnimatedContainer)));
    expect((box.decoration as BoxDecoration).color, Palette.light.surface);
    expect(tester.widget<ColoredBox>(find.descendant(of: find.byType(Backdrop), matching: find.byType(ColoredBox)).first).color, Palette.light.bg);
  });

  test('stats 块：解析、复制成“标签：数值（变化）”', () {
    final b = Block.fromJson({
      'type': 'stats',
      'items': [
        {'label': '今日最高', 'value': '26°C', 'note': '比昨天 ↑3°'},
        {'label': '日落', 'value': '17:42'},
      ]
    });
    expect(b, isA<StatsBlock>());
    expect((b as StatsBlock).items[1].note, isNull);
    expect(copyText([b]), '今日最高：26°C（比昨天 ↑3°）\n日落：17:42');
  });

  testWidgets('stats 块：短数值手机上两列并排，长数值一项一行', (tester) async {
    tester.view.physicalSize = const Size(390, 800);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    const short = StatsBlock([StatItem(label: '最高', value: '26°C'), StatItem(label: '日落', value: '17:42')]);
    await tester.pumpWidget(_wrap(const Padding(padding: EdgeInsets.all(Sp.x4), child: BlockList([short]))));
    await tester.pumpAndSettle();
    expect(find.byType(ValueTile), findsNWidgets(2));
    expect(tester.getTopLeft(find.text('26°C')).dy, tester.getTopLeft(find.text('17:42')).dy);
    expect(find.bySemanticsLabel('最高，26°C'), findsOneWidget);

    const long = StatsBlock([StatItem(label: '本月', value: '¥1,280.00 / 月'), StatItem(label: '上月', value: '¥1,100.00 / 月')]);
    await tester.pumpWidget(_wrap(const Padding(padding: EdgeInsets.all(Sp.x4), child: BlockList([long]))));
    await tester.pumpAndSettle();
    expect(tester.getTopLeft(find.text('¥1,100.00 / 月')).dy, greaterThan(tester.getTopLeft(find.text('¥1,280.00 / 月')).dy));
  });

  test('项目：那段对话 id 和最近活动（老服务端没有 → null / 退回 updated_at）', () {
    final p = Project.fromJson({'id': 'p', 'name': 'x', 'updated_at': '2026-10-01T00:00:00Z', 'conversation_id': 'c1', 'last_active_at': '2026-10-10T00:00:00Z'});
    expect(p.conversationId, 'c1');
    expect(p.activeAt, DateTime.parse('2026-10-10T00:00:00Z').toLocal());
    final old = Project.fromJson({'id': 'p', 'name': 'x', 'updated_at': '2026-10-01T00:00:00Z'});
    expect(old.conversationId, isNull);
    expect(old.activeAt, old.updatedAt);
  });

  testWidgets('建议卡：按钮一排等宽，最后一个是实心主按钮', (tester) async {
    tester.view.physicalSize = const Size(400, 900);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    final card = HomeCard.fromJson({'id': 'k', 'kind': 'action', 'title': '预算', 'blocks': [], 'action_prompt': 'x', 'target': 'usage', 'dismissed': false, 'unread': false});
    await tester.pumpWidget(ProviderScope(child: _wrap(SingleChildScrollView(child: ActionCard(card: card, onDo: (_) {}, onOpen: (_, _, {projectId}) {})))));
    await tester.pumpAndSettle();
    final pills = tester.widgetList<PillButton>(find.byType(PillButton)).toList();
    expect(pills.map((b) => b.label), ['忽略', '查看用量', '去做']);
    expect(pills.map((b) => b.primary), [false, false, true]);
    final widths = {for (final f in find.byType(PillButton).evaluate()) (f.renderObject as RenderBox).size.width.round()};
    expect(widths.length, 1);
  });

  testWidgets('我的：名字 + 域名 + 用量卡；偏好设置：头像颜色 → 选预设色，减少透明度开关落到偏好', (tester) async {
    SharedPreferences.setMockInitialValues({'server': 'https://me.example'});
    FlutterSecureStoragePlatformMock.install();
    tester.view.physicalSize = const Size(1080, 2600);
    tester.view.devicePixelRatio = 1.5;
    addTearDown(tester.view.reset);
    final c = ProviderContainer(overrides: [
      usageProvider.overrideWith(() => _FixedUsage(UsageReport.fromJson({'currency': 'CNY', 'budget': 50, 'priced': ['fast'], 'today': {}, 'month': {'cost': 12.3, 'tokens': 1000}}))),
    ]);
    addTearDown(c.dispose);
    await tester.pumpWidget(UncontrolledProviderScope(container: c, child: _wrap(const MeScreen())));
    await tester.pumpAndSettle();
    expect(find.text('me.example'), findsOneWidget);
    expect(find.text('¥12.30'), findsOneWidget);
    expect(find.text('预算 ¥50.00'), findsOneWidget);
    expect(find.byType(ListRow), findsNWidgets(9)); // 一屏：两组 9 行，行里没有副标题
    for (final r in tester.widgetList<ListRow>(find.byType(ListRow))) {
      expect(r.subtitle, isNull);
    }

    await tester.pumpWidget(UncontrolledProviderScope(container: c, child: _wrap(const PreferencesScreen())));
    await tester.pumpAndSettle();
    await tester.tap(find.text('头像颜色'));
    await tester.pumpAndSettle();
    expect(find.byType(HueWheel), findsOneWidget);
    await tester.tap(find.bySemanticsLabel('预设颜色').at(2));
    await tester.pumpAndSettle();
    expect(c.read(lookProvider).value!.avatar, AvatarColors.presets[2]);
    await tester.tapAt(tester.getCenter(find.byType(HueWheel)) + const Offset(0, -Layout.wheel / 2 + HueWheel.ring / 2)); // 环的正上方 = 色相 0
    await tester.pumpAndSettle();
    expect(HSVColor.fromColor(c.read(lookProvider).value!.avatar!).hue, closeTo(0, 2));
    await tester.tap(find.bySemanticsLabel('默认（中性）'));
    await tester.pumpAndSettle();
    expect(c.read(lookProvider).value!.avatar, isNull);
    Navigator.of(tester.element(find.byType(HueWheel))).pop();
    await tester.pumpAndSettle();

    await tester.tap(find.byKey(const Key('solid')));
    await tester.pumpAndSettle();
    expect(c.read(lookProvider).value!.solid, isTrue);
    expect(tester.takeException(), isNull);
  });

  testWidgets('我的：常见安卓手机（412×915）一屏装下，退出登录不用滚就看得到', (tester) async {
    SharedPreferences.setMockInitialValues({'server': 'https://me.example'});
    FlutterSecureStoragePlatformMock.install();
    tester.view.physicalSize = const Size(1236, 2745);
    tester.view.devicePixelRatio = 3;
    addTearDown(tester.view.reset);
    final c = ProviderContainer(overrides: [
      usageProvider.overrideWith(() => _FixedUsage(UsageReport.fromJson({'currency': 'CNY', 'priced': [], 'today': {}, 'month': {'tokens': 3100000}}))),
    ]);
    addTearDown(c.dispose);
    await tester.pumpWidget(UncontrolledProviderScope(container: c, child: _wrap(const MeScreen())));
    await tester.pumpAndSettle();
    final bottom = tester.getBottomLeft(find.byKey(const Key('logout'))).dy;
    expect(bottom, lessThanOrEqualTo(915));
  });
}

/// 固定报表（不发请求）：usageProvider 是 SwrGet（core/swr.dart）。
class _FixedUsage extends SwrGet<UsageReport> {
  _FixedUsage(UsageReport r) : super('/api/usage', (_) => r);
  @override
  Future<Object?> fetch() async => const {};
}
