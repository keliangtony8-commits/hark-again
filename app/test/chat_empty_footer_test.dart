// v3.5.5（HANDOFF v3.5.1 待查项“空态建议被输入框挡”）：新对话空态的最后一个建议不能停在输入胶囊下面——
// 放得下就整组露在胶囊上方，放不下（矮屏）就能滚到整颗露出。留白 = FloatingFooter 量出的胶囊高度（MediaQuery.padding.bottom）。
// 用户当时的截图是手机浏览器（网页版）：根因是浏览器标签页里多报的约 44px 顶部安全区把整组往下推（v3.5.1 5a733d4 已修）；
// 这里守 App 同一处，网页同一条在 frontend/scripts/shots.py 的 chat-empty 断言里。
import 'package:assistant/core/api.dart';
import 'package:assistant/core/cache.dart';
import 'package:assistant/core/chat_socket.dart';
import 'package:assistant/features/chat/chat_view.dart';
import 'package:assistant/features/chat/composer.dart';
import 'package:assistant/shell/launch_composer.dart';
import 'package:assistant/theme/app_theme.dart';
import 'package:assistant/ui/glass.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'chat_controller_test.dart' show FakeSocket;

class _Api implements Api {
  @override
  Future<dynamic> get(String path) async => path.startsWith('/api/conversations') ? <dynamic>[] : null;

  @override
  dynamic noSuchMethod(Invocation i) => throw UnimplementedError();
}

Future<void> _checkAt(WidgetTester tester, Size logical, {required bool fits}) async {
  tester.view.devicePixelRatio = 2.75;
  tester.view.physicalSize = logical * 2.75;
  tester.view.padding = const FakeViewPadding(top: 110, bottom: 66);
  tester.view.viewPadding = const FakeViewPadding(top: 110, bottom: 66);
  addTearDown(tester.view.reset);
  await tester.pumpWidget(ProviderScope(
    overrides: [
      chatSocketProvider.overrideWithValue(FakeSocket()),
      apiProvider.overrideWithValue(_Api()),
      cacheStoreProvider.overrideWithValue(MemoryCacheStore()),
    ],
    child: MaterialApp(theme: buildTheme(Brightness.light), home: const Scaffold(backgroundColor: Colors.transparent, body: ChatView(suggestions: starterPrompts))),
  ));
  await tester.pumpAndSettle(); // 第一帧量出胶囊高度，之后按它留白
  final chips = find.byType(GlassChip);
  expect(chips, findsNWidgets(starterPrompts.length));
  final last = chips.last;
  final composerTop = tester.getRect(find.byType(Composer)).top;
  if (!fits) {
    await tester.drag(find.byType(SingleChildScrollView), const Offset(0, -2000));
    await tester.pumpAndSettle();
  }
  final rect = tester.getRect(last);
  expect(rect.bottom, lessThanOrEqualTo(composerTop), reason: '最后一个建议底边 ${rect.bottom} 停在输入胶囊（顶边 $composerTop）下 @ $logical');
}

void main() {
  testWidgets('手机（用户真机视口 393×707）：四个建议整组在输入胶囊上方', (tester) => _checkAt(tester, const Size(393, 707), fits: true));
  testWidgets('412×915：四个建议整组在输入胶囊上方', (tester) => _checkAt(tester, const Size(412, 915), fits: true));
  testWidgets('矮屏 360×420：放不下时滚到底最后一个建议整颗露出、点得到', (tester) => _checkAt(tester, const Size(360, 420), fits: false));
}
