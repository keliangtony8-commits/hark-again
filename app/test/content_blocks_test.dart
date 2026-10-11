// 回复卡片补齐（v0.78）：草稿 / 摘要 / 图片三张卡——解析（非 http 图片被丢）、复制规则、
// 草稿原样显示 + 复制变对勾、摘要很长时折起并能展开/收起、短摘要不折、图片单张/多张版式与打开大图。
import 'package:assistant/blocks/block_view.dart';
import 'package:assistant/blocks/content_blocks.dart';
import 'package:assistant/models/block.dart';
import 'package:assistant/theme/app_theme.dart';
import 'package:assistant/ui/kit.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';

Future<void> pump(WidgetTester tester, Block b) async {
  tester.view.physicalSize = const Size(800, 1400);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(MaterialApp(
    theme: buildTheme(Brightness.light),
    home: Scaffold(body: SingleChildScrollView(child: BlockView(b))),
  ));
  await tester.pumpAndSettle();
}

void main() {
  const draftBody = 'Subject: 十月房租晚两天\n\n王先生您好：\n这个月房租想晚两天交。';

  test('解析 + 复制', () {
    final blocks = blocksFrom([
      {'type': 'draft', 'title': '给房东的邮件', 'body': draftBody},
      {'type': 'summary', 'title': '杭州两日行程', 'subtitle': '10 月 18–19 日', 'markdown': '## 周六\n- 断桥骑行'},
      {
        'type': 'images',
        'items': [
          {'url': 'https://img.example/a.jpg', 'caption': '白堤'},
          {'url': 'javascript:alert(1)'},
        ]
      },
    ]);
    expect(blocks[0], isA<DraftBlock>());
    expect((blocks[2] as ImagesBlock).items.map((i) => i.url), ['https://img.example/a.jpg']);
    final text = copyText(blocks);
    expect(text, contains(draftBody));
    expect(text, contains('**杭州两日行程**\n\n10 月 18–19 日\n\n## 周六'));
    expect(text, contains('- 白堤 https://img.example/a.jpg'));
    expect(SummaryBlockView.foldable('短'), isFalse);
    expect(SummaryBlockView.foldable('行\n' * 20), isTrue);
  });

  testWidgets('草稿：原样正文 + 复制变对勾', (tester) async {
    String? clip;
    tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(SystemChannels.platform, (call) async {
      if (call.method == 'Clipboard.setData') clip = (call.arguments as Map)['text'] as String;
      return null;
    });
    await pump(tester, const DraftBlock(title: '给房东的邮件', body: draftBody));
    expect(find.text('草稿 · 给房东的邮件'), findsOneWidget);
    expect(find.text(draftBody), findsOneWidget);
    expect(find.byTooltip('分享草稿'), findsOneWidget);
    await tester.tap(find.byTooltip('复制草稿'));
    await tester.pump();
    expect(clip, draftBody);
    expect(find.byTooltip('已复制'), findsOneWidget);
    await tester.pump(const Duration(seconds: 2));
    await tester.pumpAndSettle();
  });

  testWidgets('摘要：长文折起 → 展开全文 → 收起；短文不折', (tester) async {
    final long = List.generate(30, (i) => '- 第 ${i + 1} 站').join('\n');
    await pump(tester, SummaryBlock(title: '杭州两日行程', subtitle: '10 月 18–19 日', markdown: long));
    expect(find.text('杭州两日行程'), findsOneWidget);
    expect(find.text('10 月 18–19 日'), findsOneWidget);
    expect(find.byType(FoldedBox), findsOneWidget);
    await tester.tap(find.text('展开全文'));
    await tester.pumpAndSettle();
    expect(find.byType(FoldedBox), findsNothing);
    expect(find.text('收起'), findsOneWidget);
    await tester.tap(find.text('收起'));
    await tester.pumpAndSettle();
    expect(find.byType(FoldedBox), findsOneWidget);

    await pump(tester, const SummaryBlock(title: '短', markdown: '一句话'));
    expect(find.byType(FoldedBox), findsNothing);
    expect(find.text('展开全文'), findsNothing);
  });

  testWidgets('图片：单张铺满、多张横排、点开大图', (tester) async {
    await pump(tester, const ImagesBlock([ImageItem(url: 'https://img.example/a.jpg', caption: '白堤')]));
    expect(find.byType(AspectRatio), findsOneWidget);
    expect(find.text('白堤'), findsOneWidget);

    await pump(tester, const ImagesBlock([
      ImageItem(url: 'https://img.example/a.jpg', caption: '白堤'),
      ImageItem(url: 'https://img.example/b.jpg', caption: '苏堤'),
    ]));
    expect(find.byType(ListView), findsOneWidget);
    expect(find.text('苏堤'), findsOneWidget);
    await tester.tap(find.bySemanticsLabel('图片：苏堤，查看大图'));
    await tester.pumpAndSettle();
    expect(find.text('打开原图'), findsOneWidget);
    await tester.tap(find.text('关闭'));
    await tester.pumpAndSettle();
    expect(find.text('打开原图'), findsNothing);
  });
}
