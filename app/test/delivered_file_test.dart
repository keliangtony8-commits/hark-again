// 交付的文件卡（v1.22 display_file）：第二行 = [种类 · ]大小[ · 我的文件/项目文件]，规则和网页 fileKind / fileSubtitle 一致；
// 交付快照（source=upload）不带工作区名，退回的工作区文件卡带“我的文件”/“项目文件”；不认识的类型只显示大小。
import 'package:assistant/blocks/block_view.dart';
import 'package:assistant/core/api.dart';
import 'package:assistant/models/block.dart';
import 'package:assistant/theme/app_theme.dart';
import 'package:assistant/ui/format.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

class _Api implements Api {
  @override
  String fileUrl(String path) => 'http://x$path';

  @override
  dynamic noSuchMethod(Invocation i) => throw UnimplementedError();
}

void main() {
  test('种类规则', () {
    expect(fileKind('报告.PDF', 'application/pdf'), 'PDF 文档');
    expect(fileKind('site.zip', 'application/zip'), '压缩包');
    expect(fileKind('结果.xlsx', 'application/octet-stream'), '表格');
    expect(fileKind('录音.m4a', 'audio/mp4'), '音频');
    expect(fileKind('model.bin', 'application/octet-stream'), '');
    expect(fileSubtitle('model.bin', 'application/octet-stream', 2048), '2 KB');
    expect(fileSubtitle('a.csv', 'text/csv', 900, workspaceTitle: '我的文件'), '表格 · 900 B · 我的文件');
  });

  testWidgets('卡片第二行', (tester) async {
    tester.view.physicalSize = const Size(400, 800);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    final blocks = blocksFrom([
      {'type': 'file', 'source': 'upload', 'id': 'u1', 'name': '季度报告.pdf', 'mime': 'application/pdf', 'size': 3 << 20},
      {'type': 'file', 'source': 'project', 'id': 'huge.bin', 'name': 'huge.bin', 'mime': 'application/octet-stream',
       'size': 60 << 20, 'project_id': 'me'},
    ]);
    await tester.pumpWidget(ProviderScope(
      overrides: [apiProvider.overrideWithValue(_Api())],
      child: MaterialApp(
        theme: buildTheme(Brightness.light),
        home: Scaffold(body: Column(children: [for (final b in blocks) BlockView(b)])),
      ),
    ));
    await tester.pump();
    expect(find.text('PDF 文档 · 3.0 MB'), findsOneWidget);
    expect(find.text('60.0 MB · 我的文件'), findsOneWidget);
    expect(find.text('PDF'), findsOneWidget);
  });
}
