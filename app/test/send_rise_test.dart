// §O 发送气泡上弹：弹簧曲线一次过冲约 20% 后落回；只有本机刚发出的那条弹；减弱动效只淡入。
import 'package:assistant/theme/tokens.dart';
import 'package:assistant/ui/motion.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

double _dy(WidgetTester t) => t.widget<Transform>(find.descendant(of: find.byType(SendRise), matching: find.byType(Transform))).transform.getTranslation().y;

void main() {
  test('弹簧曲线：0→1，冲过终点一次（约 20%），回落后不再明显反弹', () {
    const c = SpringCurve();
    final ys = [for (var i = 0; i <= 200; i++) c.transform(i / 200)];
    expect(ys.first, 0);
    expect(ys.last, 1);
    final peak = ys.reduce((a, b) => a > b ? a : b);
    expect(peak, inInclusiveRange(1.15, 1.25));
    final after = ys.sublist(ys.indexOf(peak));
    final dip = after.reduce((a, b) => a < b ? a : b);
    expect(1 - dip, lessThan(0.06)); // 回落时的下冲很小：一次过冲，不来回抖
  });

  testWidgets('play：从下方上来、冲过终点再落回；play=false 原样不动', (t) async {
    await t.pumpWidget(const Directionality(textDirection: TextDirection.ltr, child: SendRise(play: true, child: Text('hi'))));
    expect(_dy(t), closeTo(Motion.sendRise, 0.01));
    var minDy = 0.0;
    for (var i = 0; i < 30; i++) {
      await t.pump(const Duration(milliseconds: 16));
      if (_dy(t) < minDy) minDy = _dy(t);
    }
    expect(minDy, lessThan(-3)); // 过冲到终点上方几 px
    await t.pumpAndSettle();
    expect(_dy(t), 0);

    await t.pumpWidget(const Directionality(textDirection: TextDirection.ltr, child: SendRise(play: false, child: Text('hi'))));
    expect(_dy(t), 0);
  });

  testWidgets('减弱动效：只淡入不位移', (t) async {
    await t.pumpWidget(const MediaQuery(
      data: MediaQueryData(disableAnimations: true),
      child: Directionality(textDirection: TextDirection.ltr, child: SendRise(play: true, child: Text('hi'))),
    ));
    await t.pump(const Duration(milliseconds: 60));
    expect(_dy(t), 0);
    expect(t.widget<Opacity>(find.byType(Opacity)).opacity, lessThan(1));
    await t.pumpAndSettle();
  });
}
