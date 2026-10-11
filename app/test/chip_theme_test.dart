// 选择胶囊（ChoiceChip）的外观只来自主题 chipTheme：胶囊形、无描边，选中墨色 / 未选 tile（v1.06）。
import 'package:assistant/theme/app_theme.dart';
import 'package:assistant/theme/tokens.dart';
import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart' show RenderParagraph;
import 'package:flutter_test/flutter_test.dart';

void main() {
  for (final (b, p) in [(Brightness.light, Palette.light), (Brightness.dark, Palette.dark)]) {
    test('chipTheme 胶囊 · 选中墨色（$b）', () {
      final c = buildTheme(b).chipTheme;
      expect(c.shape, isA<StadiumBorder>());
      expect(c.side?.color, Colors.transparent);
      expect(c.showCheckmark, isFalse);
      expect(c.color!.resolve({WidgetState.selected}), p.ink);
      expect(c.color!.resolve({}), p.tile);
      expect(c.secondaryLabelStyle!.color, p.onInk);
      expect(c.labelStyle!.color, p.text2);
    });
  }

  testWidgets('ChoiceChip 选中时字是 onInk', (tester) async {
    await tester.pumpWidget(MaterialApp(
      theme: buildTheme(Brightness.light),
      home: Scaffold(body: Row(children: [
        ChoiceChip(label: const Text('全部 5'), selected: true, onSelected: (_) {}),
        ChoiceChip(label: const Text('饮食 1'), selected: false, onSelected: (_) {}),
      ])),
    ));
    Color? colorOf(String text) {
      Color? c;
      tester.renderObject<RenderParagraph>(find.text(text)).text.visitChildren((span) {
        c = span.style?.color ?? c;
        return true;
      });
      return c ?? tester.renderObject<RenderParagraph>(find.text(text)).text.style?.color;
    }
    expect(colorOf('全部 5'), Palette.light.onInk);
    expect(colorOf('饮食 1'), Palette.light.text2);
  });
}
