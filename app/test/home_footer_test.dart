// v2.94（HANDOFF 6a ②）：主页底部输入胶囊不能盖住最后一张卡。留白不是写死的数，是 FloatingFooter 量出的胶囊实际高度
// （含底部安全区）经 MediaQuery.padding.bottom 交给 PageBody。主页的组合 = ShellPage → LaunchComposer → PageBody，
// 这里原样搭起来，手机和电脑两种宽度各滚到底，量最后一张卡的底边和胶囊顶边。
import 'package:assistant/features/chat/composer.dart';
import 'package:assistant/shell/launch_composer.dart';
import 'package:assistant/shell/shell_page.dart';
import 'package:assistant/theme/app_theme.dart';
import 'package:assistant/ui/kit.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

const _last = ValueKey('last-card');

Widget _home() => ProviderScope(
      child: MaterialApp(
        theme: buildTheme(Brightness.light),
        home: Scaffold(
          backgroundColor: Colors.transparent,
          body: ShellPage(
            child: LaunchComposer(
              child: PageBody(children: [
                for (var i = 0; i < 8; i++) Container(height: 220, margin: const EdgeInsets.only(bottom: 16), color: Colors.black12),
                Container(key: _last, height: 64, color: Colors.black26),
              ]),
            ),
          ),
        ),
      ),
    );

Future<void> _checkAt(WidgetTester tester, Size logical, double bottomInset) async {
  tester.view.devicePixelRatio = 2;
  tester.view.physicalSize = logical * 2;
  tester.view.padding = FakeViewPadding(top: 48, bottom: bottomInset * 2);
  tester.view.viewPadding = FakeViewPadding(top: 48, bottom: bottomInset * 2);
  addTearDown(tester.view.reset);
  await tester.pumpWidget(_home());
  await tester.pump();
  await tester.pump(); // 第一帧量出胶囊高度，第二帧按它留白
  await tester.drag(find.byType(ListView), const Offset(0, -20000));
  await tester.pumpAndSettle();
  final card = tester.getRect(find.byKey(_last));
  final composer = tester.getRect(find.byType(Composer));
  expect(card.bottom, lessThanOrEqualTo(composer.top), reason: '最后一张卡底边 ${card.bottom} 被胶囊（顶边 ${composer.top}）盖住 @ $logical');
}

void main() {
  testWidgets('手机：滚到底最后一张卡在输入胶囊上方（含手势条安全区）', (tester) => _checkAt(tester, const Size(412, 892), 24));
  testWidgets('电脑宽屏：滚到底最后一张卡在输入胶囊上方', (tester) => _checkAt(tester, const Size(1440, 900), 0));
}
