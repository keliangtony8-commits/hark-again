// v2.28 浏览器服务本身不能用（后端 BrowserDown → 卡上 down）：解析（空串当没有）、画面位置换成原因 + 怎么办、
// 不连实时画面、不能接管、没有实时红点；换成正常新卡后画面连上。
import 'package:assistant/blocks/block_view.dart';
import 'package:assistant/blocks/browser_live.dart';
import 'package:assistant/core/api.dart';
import 'package:assistant/models/block.dart';
import 'package:assistant/models/browser_view.dart';
import 'package:assistant/theme/app_theme.dart';
import 'package:assistant/ui/motion.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'browser_handoff_test.dart' show FakeLives;

class FakeApi implements Api {
  @override
  String fileUrl(String path) => 'http://test.invalid$path?token=t';

  @override
  dynamic noSuchMethod(Invocation i) => throw UnimplementedError();
}

Map<String, dynamic> card({String? down}) => {
      'type': 'browser',
      'session': 'a-com',
      'site': 'a.com',
      'down': ?down,
    };

Widget host(FakeLives lives, Map<String, dynamic> j) => ProviderScope(
      overrides: [apiProvider.overrideWithValue(FakeApi()), liveConnectProvider.overrideWithValue(lives.connect)],
      child: MaterialApp(
        theme: buildTheme(Brightness.light),
        home: Scaffold(body: SingleChildScrollView(child: BlockView(Block.fromJson(j)))),
      ),
    );

void main() {
  test('解析：down 可选，空白当作没有', () {
    expect((Block.fromJson(card(down: ' 缺少系统库 libatk-1.0.so.0 ')) as BrowserBlock).down, '缺少系统库 libatk-1.0.so.0');
    expect((Block.fromJson(card()) as BrowserBlock).down, isNull);
    expect((Block.fromJson(card(down: '  ')) as BrowserBlock).down, isNull);
  });

  testWidgets('服务坏了：显示原因和怎么办，不拉画面、不能接管；换成正常卡后画面回来', (tester) async {
    tester.view.physicalSize = const Size(500, 1000);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    final lives = FakeLives();
    await tester.pumpWidget(host(lives, card(down: '缺少系统库 libatk-1.0.so.0')));
    await tester.pump(const Duration(seconds: 3));
    expect(find.text(browserDownTitle), findsOneWidget);
    expect(find.text('缺少系统库 libatk-1.0.so.0'), findsOneWidget);
    expect(find.text(browserDownHint), findsOneWidget);
    expect(find.text('接管'), findsNothing);
    expect(find.byType(PulseDot), findsNothing);
    expect(find.byType(Image), findsNothing);
    expect(lives.all, isEmpty);

    await tester.pumpWidget(host(lives, card()));
    for (var i = 0; i < 6; i++) {
      await tester.pump(const Duration(milliseconds: 100));
    }
    expect(find.text(browserDownTitle), findsNothing);
    expect(find.text('接管'), findsOneWidget);
    expect(lives.all, hasLength(1));
    await tester.pumpWidget(const SizedBox());
    await tester.pump(const Duration(seconds: 1));
  });
}
