// 回归（v0.90）：描边式边框让浮起的标签骑在透明边线上、半截掉出填充块。
// 现在主题用 FieldBorder（填充式）：有内容时标签浮在填充块里面。
import 'package:assistant/theme/app_theme.dart';
import 'package:assistant/theme/field_border.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  testWidgets('浮起的标签在填充块里面', (tester) async {
    tester.view.devicePixelRatio = 1;
    tester.view.physicalSize = const Size(400, 400);
    addTearDown(tester.view.reset);
    final theme = buildTheme(Brightness.light);
    expect(theme.inputDecorationTheme.border, isA<FieldBorder>());
    expect(theme.inputDecorationTheme.border!.isOutline, isFalse);

    await tester.pumpWidget(MaterialApp(
      theme: theme,
      home: Scaffold(
        body: Padding(
          padding: const EdgeInsets.all(40),
          child: TextField(controller: TextEditingController(text: '柯妈妈'), decoration: const InputDecoration(labelText: '收件人')),
        ),
      ),
    ));
    await tester.pumpAndSettle();
    final field = tester.getRect(find.byType(InputDecorator));
    final label = tester.getRect(find.text('收件人'));
    expect(label.top, greaterThanOrEqualTo(field.top));
    expect(label.bottom, lessThan(tester.getRect(find.text('柯妈妈')).top + 1));
  });

  test('FieldBorder 相等与缩放', () {
    const a = FieldBorder(radius: 12);
    expect(a, const FieldBorder(radius: 12));
    expect((a.scale(2) as FieldBorder).radius, 24);
    expect(a.copyWith(borderSide: const BorderSide(width: 2)).borderSide.width, 2);
  });
}
