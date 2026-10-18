// v3.5.2 外壳壁纸被不透明子页完全盖住时连画都不画（app_shell.dart SkipWhenCovered，jank 诊断方案 2）：
// Impeller 每帧重放整棵 display list，只停时钟（SkyCover，v3.3 B4）它仍每帧整屏跑着色器。
// 转场中照常画；盖住后外壳那层壁纸不进图层树；返回一开始就恢复。
import 'dart:async';

import 'package:assistant/shell/app_shell.dart';
import 'package:assistant/theme/app_theme.dart';
import 'package:assistant/ui/glass.dart';
import 'package:assistant/ui/motion.dart';
import 'package:assistant/ui/sky.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

/// 数自己被画了几次。
class _Count extends CustomPainter {
  int n = 0;
  @override
  void paint(Canvas canvas, Size size) => n++;
  @override
  bool shouldRepaint(_Count old) => false;
}

void main() {
  Widget host(Widget child) => MaterialApp(theme: buildTheme(Brightness.light), home: child);

  testWidgets('子页进场完成后外壳壁纸不画；转场中、返回一开始都照常画', (tester) async {
    final c = SkyClock.forTest(frozen: true);
    final nav = GlobalKey<NavigatorState>();
    final count = _Count();
    await tester.pumpWidget(host(SkyCoverScope(
      child: Stack(children: [
        Positioned.fill(child: SkipWhenCovered(child: Stack(children: [Positioned.fill(child: SkyLayer(coverable: true, clock: c)), Positioned.fill(child: CustomPaint(painter: count))]))),
        Navigator(key: nav, onGenerateRoute: (_) => PageRouteBuilder<void>(opaque: false, pageBuilder: (_, _, _) => const SizedBox.expand())),
      ]),
    )));
    RenderSkipWhenCovered gate() => tester.renderObject<RenderSkipWhenCovered>(find.byType(SkipWhenCovered));
    bool shellSkyInTree() => find.byWidgetPredicate((w) => w is SkyLayer && w.coverable).evaluate().isNotEmpty;
    expect(gate().skipped, isFalse);
    final before = count.n;
    expect(before, greaterThan(0));

    unawaited(nav.currentState!.push(MaterialPageRoute<void>(builder: (_) => const SkyCover(child: Backdrop(child: Text('子页'))))));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 100));
    expect(gate().skipped, isFalse, reason: '转场中外壳壁纸必须照常画');

    await tester.pumpAndSettle();
    expect(gate().skipped, isTrue, reason: '被不透明子页完全盖住：不画');
    expect(shellSkyInTree(), isTrue, reason: '子树保留（状态不丢），只是不画');
    // 强制整页重画：盖住期间外壳那层一次都不画
    final covered = count.n;
    tester.renderObject(find.byType(SkipWhenCovered)).markNeedsPaint();
    await tester.pump();
    expect(count.n, covered);

    nav.currentState!.pop();
    expect(gate().skipped, isFalse, reason: 'pop 一开始就恢复，先于第一帧转场');
    expect(gate().debugNeedsPaint, isTrue);
    await tester.pump();
    expect(count.n, greaterThan(covered));
    await tester.pumpAndSettle();
    expect(find.text('子页'), findsNothing);
    expect(tester.takeException(), isNull);
  });

  testWidgets('没有 SkyCoverScope：照常画', (tester) async {
    final count = _Count();
    await tester.pumpWidget(host(SkipWhenCovered(child: CustomPaint(painter: count, child: const SizedBox.expand()))));
    expect(tester.renderObject<RenderSkipWhenCovered>(find.byType(SkipWhenCovered)).skipped, isFalse);
    expect(count.n, greaterThan(0));
  });
}
