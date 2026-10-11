// RowTile(dimmed:)：关着的项图标和文字变淡，行尾开关不跟着淡（v1.08，技能/任务行）。
import 'package:assistant/theme/app_theme.dart';
import 'package:assistant/theme/tokens.dart';
import 'package:assistant/ui/kit.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

double opacityAbove(WidgetTester t, Finder f) {
  var o = 1.0;
  for (final w in t.widgetList<AnimatedOpacity>(find.ancestor(of: f, matching: find.byType(AnimatedOpacity)))) {
    o *= w.opacity;
  }
  return o;
}

void main() {
  testWidgets('dimmed row fades text, keeps the switch crisp', (t) async {
    await t.pumpWidget(MaterialApp(
      theme: buildTheme(Brightness.light),
      home: Scaffold(
        body: RowTile(
          dimmed: true,
          icon: Icons.auto_awesome_outlined,
          title: '购物比价',
          subtitle: '找货、比价',
          trailing: Switch(value: false, onChanged: (_) {}),
        ),
      ),
    ));
    await t.pumpAndSettle();
    expect(opacityAbove(t, find.text('购物比价')), Op.dimmed);
    expect(opacityAbove(t, find.byType(Switch)), 1.0);
  });

  testWidgets('not dimmed = full strength', (t) async {
    await t.pumpWidget(MaterialApp(
      theme: buildTheme(Brightness.light),
      home: const Scaffold(body: RowTile(title: '网页调研')),
    ));
    expect(opacityAbove(t, find.text('网页调研')), 1.0);
  });
}
