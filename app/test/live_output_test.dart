// 前台命令实时输出（v1.24）：code 块 live=true → 标题旁“运行中”、不给复制、空输出显示“等待输出…”；
// 服务器 block.update 换成最终块（没有 live）→ 复制按钮回来、显示完整输出。
import 'package:assistant/blocks/block_view.dart';
import 'package:assistant/models/block.dart';
import 'package:assistant/theme/app_theme.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

Widget _host(Block b) => ProviderScope(
  child: MaterialApp(
    theme: buildTheme(Brightness.light),
    home: Scaffold(body: SingleChildScrollView(child: BlockView(b))),
  ),
);

void main() {
  test('解析 live', () {
    final b = blocksFrom([
      {'type': 'code', 'language': 'bash', 'title': r'$ pip install a', 'source': '', 'live': true},
      {'type': 'code', 'source': 'x'},
    ]);
    expect((b[0] as CodeBlock).live, isTrue);
    expect((b[1] as CodeBlock).live, isFalse);
  });

  testWidgets('运行中 → 跑完', (tester) async {
    tester.view.physicalSize = const Size(400, 800);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    const title = r'$ pip install a';
    await tester.pumpWidget(_host(const CodeBlock(language: 'bash', title: title, source: '', live: true)));
    await tester.pump(const Duration(milliseconds: 400));
    expect(find.text('运行中'), findsOneWidget);
    expect(find.text('等待输出…'), findsOneWidget);
    expect(find.byTooltip('复制'), findsNothing);

    final long = List.generate(60, (i) => 'line $i').join('\n');
    await tester.pumpWidget(_host(CodeBlock(language: 'bash', title: title, source: long, live: true)));
    await tester.pump(const Duration(milliseconds: 400));
    expect(tester.getSize(find.byType(SingleChildScrollView).at(1)).height, lessThanOrEqualTo(280));
    expect(find.textContaining('line 59'), findsOneWidget);

    await tester.pumpWidget(_host(const CodeBlock(language: 'bash', title: title, source: 'done\n# 退出码 0')));
    await tester.pumpAndSettle();
    expect(find.text('运行中'), findsNothing);
    expect(find.byTooltip('复制'), findsOneWidget);
    expect(find.textContaining('退出码 0'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
}
