// 面板关键数字滚动：NumberParts 只认“恰好一个数字”，格式（前后缀/小数/千分位）原样写回；
// CountUp 入场从 0 滚上来、值变了从旧值滚到新值、换形状直接换字、减少动态直接给终值；FadeSwitcher 换态交叉淡化。
import 'package:assistant/theme/app_theme.dart';
import 'package:assistant/theme/tokens.dart';
import 'package:assistant/ui/format.dart';
import 'package:assistant/ui/glass.dart';
import 'package:assistant/ui/motion.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

Future<void> pump(WidgetTester tester, Widget child, {bool reduce = false}) async {
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(MaterialApp(
    theme: buildTheme(Brightness.light),
    home: MediaQuery(
      data: MediaQueryData(disableAnimations: reduce),
      child: Scaffold(body: Center(child: child)),
    ),
  ));
}

String shown(WidgetTester tester) => tester.widget<Text>(find.byType(Text).first).data!;

void main() {
  test('NumberParts 解析与回写', () {
    final m = NumberParts.parse('¥1,280.50 / 月')!;
    expect((m.prefix, m.value, m.decimals, m.grouped, m.suffix), ('¥', 1280.5, 2, true, ' / 月'));
    expect(m.format(999.5), '¥999.50 / 月');
    expect(m.format(12345.678), '¥12,345.68 / 月');
    final p = NumberParts.parse('+1.2%')!;
    expect((p.prefix, p.value, p.suffix), ('+', 1.2, '%'));
    expect(p.format(0.6), '+0.6%');
    expect(NumberParts.parse('26°C')!.format(13), '13°C');
    for (final s in ['17:42', '2026-10-11', '3/5', '晴', '', '1,2,3', '12345678901234567']) {
      expect(NumberParts.parse(s), isNull, reason: s);
    }
  });

  testWidgets('入场从 0 滚上来，结束停在原字', (tester) async {
    await pump(tester, const CountUp('¥1,280.50'));
    expect(shown(tester), '¥0.00');
    await tester.pump(Motion.count ~/ 2);
    final mid = NumberParts.parse(shown(tester))!.value;
    expect(mid, greaterThan(0));
    expect(mid, lessThan(1280.5));
    await tester.pumpAndSettle();
    expect(shown(tester), '¥1,280.50');
  });

  testWidgets('值变了从旧值滚到新值；换形状直接换字', (tester) async {
    await pump(tester, const CountUp('26°C'));
    await tester.pumpAndSettle();
    await pump(tester, const CountUp('20°C'));
    expect(shown(tester), '26°C'); // 从旧值起，不是从 0
    await tester.pump(Motion.count ~/ 2);
    final mid = NumberParts.parse(shown(tester))!.value;
    expect(mid, inExclusiveRange(20, 26));
    await tester.pumpAndSettle();
    expect(shown(tester), '20°C');
    await pump(tester, const CountUp('17:42'));
    expect(shown(tester), '17:42');
    await pump(tester, const CountUp('3 件'));
    expect(shown(tester), '3 件'); // 上一个不是数字：不滚
  });

  testWidgets('减少动态：直接给终值', (tester) async {
    await pump(tester, const CountUp('¥88'), reduce: true);
    expect(shown(tester), '¥88');
  });

  testWidgets('ValueTile 读屏念终值，大数字走 CountUp', (tester) async {
    final h = tester.ensureSemantics();
    await pump(tester, const SizedBox(width: 200, child: ValueTile(label: '余额', value: '¥1,280')));
    expect(find.byType(CountUp), findsOneWidget);
    expect(find.bySemanticsLabel('余额，¥1,280'), findsOneWidget);
    await tester.pumpAndSettle();
    h.dispose();
  });

  testWidgets('FadeSwitcher：换 key 交叉淡化，同 key 不过渡', (tester) async {
    Widget sw(String k, String text) => FadeSwitcher(child: Text(text, key: ValueKey(k)));
    await pump(tester, sw('loading', '骨架'));
    await pump(tester, sw('list', '内容'));
    await tester.pump(Motion.base ~/ 2);
    expect(find.text('骨架'), findsOneWidget); // 旧的还在淡出
    expect(find.text('内容'), findsOneWidget);
    await tester.pumpAndSettle();
    expect(find.text('骨架'), findsNothing);
    await pump(tester, sw('list', '内容 2'));
    await tester.pump();
    expect(find.text('内容'), findsNothing); // 同态更新：直接换
    expect(find.text('内容 2'), findsOneWidget);
  });
}
