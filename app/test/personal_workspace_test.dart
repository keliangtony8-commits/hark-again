// 主聊天也有“电脑”（v1.21）：个人工作区 id 'me'（core/workspace.dart，和服务器 workspaces.py 一致）；
// 文件抽屉对 'me' 叫“我的文件”、空时说明主聊天能用；附件名片第二行写“我的文件 · 大小”。
import 'package:assistant/core/api.dart';
import 'package:assistant/core/workspace.dart';
import 'package:assistant/features/chat/attachment_tray.dart';
import 'package:assistant/features/projects/project_files_sheet.dart';
import 'package:assistant/models/block.dart';
import 'package:assistant/theme/app_theme.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

class _Api implements Api {
  final gets = <String>[];
  @override
  Future<dynamic> get(String path) async {
    gets.add(path);
    return <dynamic>[];
  }

  @override
  dynamic noSuchMethod(Invocation i) => throw UnimplementedError();
}

void main() {
  test('工作区规则：主聊天 = me，项目 = 项目 id', () {
    expect(workspaceOf(''), personalWorkspace);
    expect(workspaceOf('p1'), 'p1');
    expect(workspaceFilesTitle('me'), '我的文件');
    expect(workspaceFilesTitle('p1'), '项目文件');
    expect(Attachment.ref(const FileBlock(source: 'project', id: 'a.csv', name: 'a.csv', mime: 'text/csv', size: 300, projectId: 'me')).sub,
        '我的文件 · 300 B');
  });

  testWidgets('“我的文件”抽屉：读 /api/projects/me/files，空时说明主聊天能用', (tester) async {
    tester.view.physicalSize = const Size(400, 800);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    final api = _Api();
    await tester.pumpWidget(ProviderScope(
      overrides: [apiProvider.overrideWithValue(api)],
      child: MaterialApp(
        theme: buildTheme(Brightness.light),
        home: Scaffold(body: Builder(builder: (context) => TextButton(onPressed: () => showProjectFiles(context, personalWorkspace), child: const Text('开')))),
      ),
    ));
    await tester.tap(find.text('开'));
    for (var i = 0; i < 10; i++) {
      await tester.pump(const Duration(milliseconds: 100));
    }
    expect(api.gets, contains('/api/projects/me/files'));
    expect(find.text('我的文件'), findsOneWidget);
    expect(find.textContaining('主聊天'), findsOneWidget);
  });
}
