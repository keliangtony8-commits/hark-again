// 底部提示（ui/kit.dart showToast，= 网页 ui/toast.tsx）照 Hark：短提示约 2 秒消失、带按钮的也定时消失、新替旧不排队、点一下 / 下滑关掉；
// 开着无障碍服务（Flyme 上常见：任何无障碍服务读一次界面，Flutter 就报 accessibleNavigation = true）时同样规则。
// 起因：2026-10-19 用户真机“提示出现后很久都不消失，不止一个”。旧写法连点 5 次（间隔 0.3 秒）最后一条 15 秒才消失；带“撤销”的永远不消失。
import 'package:assistant/theme/app_theme.dart';
import 'package:assistant/theme/tokens.dart';
import 'package:assistant/ui/kit.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

const _exit = Duration(milliseconds: 400); // 退场动画走完的余量

/// 按 50ms 一帧走过 [d]（一次 pump 大段时间只出一帧，入场动画走不完、计时器也就不开始，测不出真实节奏）。
Future<void> _wait(WidgetTester tester, Duration d) async {
  for (var t = Duration.zero; t < d; t += const Duration(milliseconds: 50)) {
    await tester.pump(const Duration(milliseconds: 50));
  }
}

Future<BuildContext> _pump(WidgetTester tester, {bool a11y = false}) async {
  if (a11y) {
    tester.platformDispatcher.accessibilityFeaturesTestValue = const FakeAccessibilityFeatures(accessibleNavigation: true);
    addTearDown(tester.platformDispatcher.clearAccessibilityFeaturesTestValue);
  }
  late BuildContext ctx;
  await tester.pumpWidget(MaterialApp(
    theme: buildTheme(Brightness.light),
    home: Scaffold(body: Builder(builder: (c) {
      ctx = c;
      return const SizedBox.expand();
    })),
  ));
  return ctx;
}

void main() {
  for (final a11y in [false, true]) {
    final tag = a11y ? '（无障碍开）' : '';

    testWidgets('短提示 ${Timing.toast.inSeconds} 秒后自动消失$tag', (tester) async {
      final ctx = await _pump(tester, a11y: a11y);
      showToast(ctx, '已复制');
      await tester.pumpAndSettle();
      expect(find.text('已复制'), findsOneWidget);
      await _wait(tester, Timing.toast - const Duration(milliseconds: 300));
      expect(find.text('已复制'), findsOneWidget, reason: '不会一闪就没');
      await _wait(tester, const Duration(milliseconds: 300) + _exit);
      await tester.pumpAndSettle();
      expect(find.byType(SnackBar), findsNothing);
    });

    testWidgets('带“撤销”的也定时消失（Flutter 默认带 action 就 persist，必须显式关）$tag', (tester) async {
      final ctx = await _pump(tester, a11y: a11y);
      var undone = 0;
      showToast(ctx, '已移除', action: '撤销', onAction: () => undone++);
      await tester.pumpAndSettle();
      expect(find.text('撤销'), findsOneWidget);
      await _wait(tester, Timing.toast);
      expect(find.text('撤销'), findsOneWidget, reason: '带按钮的多留一会儿，够点到');
      await _wait(tester, Timing.toastAction - Timing.toast + _exit);
      await tester.pumpAndSettle();
      expect(find.byType(SnackBar), findsNothing);
      expect(undone, 0);
    });

    testWidgets('连点不排队：新替旧，最后一条照样 ${Timing.toast.inSeconds} 秒消失$tag', (tester) async {
      final ctx = await _pump(tester, a11y: a11y);
      for (var i = 0; i < 5; i++) {
        showToast(ctx, '第 $i 条');
        await _wait(tester, const Duration(milliseconds: 300));
        expect(find.byType(SnackBar), findsOneWidget, reason: '同一时刻只有一条');
        expect(find.text('第 $i 条'), findsOneWidget, reason: '新的立刻替掉旧的');
      }
      await _wait(tester, Timing.toast + _exit);
      await tester.pumpAndSettle();
      expect(find.byType(SnackBar), findsNothing, reason: '旧写法这里还要再排两条，各放满时长');
    });
  }

  testWidgets('点一下关掉', (tester) async {
    final ctx = await _pump(tester);
    showToast(ctx, '已保存');
    await tester.pumpAndSettle();
    await tester.tap(find.text('已保存'));
    await tester.pumpAndSettle();
    expect(find.byType(SnackBar), findsNothing);
  });

  testWidgets('往下滑关掉', (tester) async {
    final ctx = await _pump(tester);
    showToast(ctx, '已保存');
    await tester.pumpAndSettle();
    await tester.fling(find.text('已保存'), const Offset(0, 200), 1000);
    await tester.pumpAndSettle();
    expect(find.byType(SnackBar), findsNothing);
  });

  testWidgets('点“撤销”调回调并收起', (tester) async {
    final ctx = await _pump(tester);
    var undone = 0;
    showToast(ctx, '已移除', action: '撤销', onAction: () => undone++);
    await tester.pumpAndSettle();
    await tester.tap(find.text('撤销'));
    await tester.pumpAndSettle();
    expect(undone, 1);
    expect(find.byType(SnackBar), findsNothing);
  });
}
