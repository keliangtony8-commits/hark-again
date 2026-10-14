// 浏览器 ⇄ 工作区文件（v1.32）：BrowserBlock.files/workspace 解析、models/browser_view.dart 文案、
// core/workspace.dart workspaceFilePath 编码，画面卡下列出传上去 / 下载下来的文件（没有 workspace 不列）。
import 'package:assistant/blocks/block_view.dart';
import 'package:assistant/blocks/browser_live.dart';
import 'package:assistant/core/api.dart';
import 'package:assistant/core/workspace.dart';
import 'package:assistant/models/block.dart';
import 'package:assistant/models/browser_view.dart';
import 'package:assistant/theme/app_theme.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'browser_handoff_test.dart' show FakeLives;

class _Api implements Api {
  @override
  String fileUrl(String path) => 'http://test.invalid$path?token=t';
  @override
  dynamic noSuchMethod(Invocation i) => throw UnimplementedError();
}

Map<String, dynamic> card({bool withWs = true}) => {
      'type': 'browser',
      'session': 'jobs-com',
      'site': 'jobs.com',
      'files': [
        {'kind': 'upload', 'name': '简历.pdf', 'path': 'cv/简历.pdf'},
        {'kind': 'download', 'name': '账单 (2).csv', 'path': 'downloads/账单 (2).csv'},
        {'kind': 'weird', 'name': 'x'}, // 没有 path：丢掉
      ],
      if (withWs) 'workspace': 'me',
    };

Future<void> pump(WidgetTester tester, Map<String, dynamic> j) async {
  tester.view.physicalSize = const Size(500, 1200);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(ProviderScope(
    overrides: [apiProvider.overrideWithValue(_Api()), liveConnectProvider.overrideWithValue(FakeLives().connect)],
    child: MaterialApp(
      theme: buildTheme(Brightness.light),
      home: Scaffold(body: SingleChildScrollView(child: BlockView(Block.fromJson(j)))),
    ),
  ));
  await tester.pump(const Duration(milliseconds: 600));
}

Future<void> unmount(WidgetTester tester) async {
  await tester.pumpWidget(const SizedBox());
  await tester.pump(const Duration(seconds: 1));
}

void main() {
  test('解析与文案', () {
    final b = Block.fromJson(card()) as BrowserBlock;
    expect(b.workspace, 'me');
    expect(b.files.map((f) => (f.kind, f.path)).toList(), [('upload', 'cv/简历.pdf'), ('download', 'downloads/账单 (2).csv')]);
    expect(b.files.first.uploaded, isTrue);
    expect(browserFileLine(b.files[0]), '已传到网页');
    expect(browserFileLine(b.files[1]), '已存到 downloads');
    expect(browserFileLine(const BrowserFile(kind: 'download', name: 'a', path: 'a')), '已存到工作区');
    expect(browserFileSemantics(b.files[1]), '账单 (2).csv，已存到 downloads，点开查看');
    final old = Block.fromJson({'type': 'browser', 'session': 'x'}) as BrowserBlock;
    expect(old.files, isEmpty);
    expect(old.workspace, isNull);
    expect(workspaceFilePath('me', 'downloads/账单 (2).csv'), '/api/projects/me/files/downloads/${Uri.encodeComponent('账单 (2).csv')}');
  });

  testWidgets('画面卡下列出文件；没有 workspace 不列', (tester) async {
    await pump(tester, card());
    expect(find.text('简历.pdf'), findsOneWidget);
    expect(find.text('已传到网页'), findsOneWidget);
    expect(find.text('账单 (2).csv'), findsOneWidget);
    expect(find.text('已存到 downloads'), findsOneWidget);
    expect(find.bySemanticsLabel('简历.pdf，已传到网页，点开查看'), findsOneWidget);
    expect(tester.takeException(), isNull);
    await unmount(tester);
    await pump(tester, card(withWs: false));
    expect(find.text('简历.pdf'), findsNothing);
    await unmount(tester);
  });
}
