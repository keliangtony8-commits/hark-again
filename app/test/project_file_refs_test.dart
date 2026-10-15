// 引用工作区文件（v1.13；v1.21 主聊天 = “我的文件”）：输入框“添加附件”多一个从工作区选（项目 = 项目文件，主聊天 = 我的文件）；
// 选择器可多选，已在托盘里的显示“已在这条消息里”不能再选；确认后托盘出现带文件夹记号的引用，发出去是 source=project 的文件块；
// 控制器把上传附件和项目文件分开发（attachments / project_files）。
import 'package:assistant/core/api.dart';
import 'package:assistant/core/cache.dart';
import 'package:assistant/core/chat_socket.dart';
import 'dart:io';

import 'package:assistant/features/chat/attachment_tray.dart';
import 'package:assistant/features/chat/chat_controller.dart';
import 'package:assistant/features/chat/composer.dart';
import 'package:assistant/features/projects/project_files_sheet.dart';
import 'package:assistant/models/block.dart';
import 'package:assistant/models/resources.dart';
import 'package:assistant/theme/app_theme.dart';
import 'package:assistant/ui/glass.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'chat_controller_test.dart' show FakeSocket;

class _Api implements Api {
  @override
  Future<dynamic> get(String path) async {
    if (path == '/api/projects/me/files') {
      return [
        {'path': '结果.csv', 'name': '结果.csv', 'size': 120, 'mime': 'text/csv'},
      ];
    }
    if (path == '/api/projects/p1/files') {
      return [
        {'path': 'notes/大纲.md', 'name': '大纲.md', 'size': 2048, 'mime': 'text/markdown'},
        {'path': '词表.csv', 'name': '词表.csv', 'size': 900, 'mime': 'text/csv'},
        {'path': '照片.png', 'name': '照片.png', 'size': 5000, 'mime': 'image/png'},
      ];
    }
    if (path.startsWith('/api/conversations')) return <dynamic>[];
    return null;
  }

  @override
  dynamic noSuchMethod(Invocation i) => throw UnimplementedError();
}

Future<void> _settle(WidgetTester tester) async {
  for (var i = 0; i < 10; i++) {
    await tester.pump(const Duration(milliseconds: 100));
  }
}

Future<List<FileBlock>> _pump(WidgetTester tester, {String? projectId = 'me'}) async {
  tester.view.physicalSize = const Size(400, 800);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  final sent = <FileBlock>[];
  await tester.pumpWidget(ProviderScope(
    overrides: [apiProvider.overrideWithValue(_Api())],
    child: MaterialApp(
      theme: buildTheme(Brightness.light),
      home: Scaffold(
        body: Align(
          alignment: Alignment.bottomCenter,
          child: Composer(workspace: projectId, busy: false, onSend: (_, files) => sent.addAll(files)),
        ),
      ),
    ),
  ));
  await _settle(tester);
  return sent;
}

void main() {
  test('附件名片第二行：上传中 / 大小 / 项目文件 · 大小；本机图片才画缩略图', () {
    final up = Attachment(name: '课表.pdf', local: File('/tmp/x.pdf'));
    expect(up.sub, '上传中…');
    expect(up.ext, 'PDF');
    up.file = const FileBlock(source: 'upload', id: 'u1', name: '课表.pdf', mime: 'application/pdf', size: 2048);
    expect(up.sub, '2 KB');
    final ref = Attachment.ref(const FileBlock(source: 'project', id: 'a/b.png', name: 'b.png', mime: 'image/png', size: 300, projectId: 'p1'));
    expect(ref.sub, '项目文件 · 300 B');
    expect(ref.asThumb, isFalse); // 项目里的图片没有本地文件
    expect(Attachment(name: '照片.jpg', local: File('/tmp/y.jpg')).asThumb, isTrue);
    expect(Attachment(name: 'archive.tar.gzip', local: File('/tmp/z')).ext, 'GZIP');
  });

  test('projectFileBlock：source=project，id 是相对路径', () {
    const f = ProjectFile(path: 'notes/大纲.md', name: '大纲.md', size: 3, mime: 'text/markdown');
    final b = projectFileBlock('p1', f);
    expect((b.source, b.id, b.name, b.projectId), ('project', 'notes/大纲.md', '大纲.md', 'p1'));
    expect(b.path, '/api/projects/p1/files/notes/大纲.md');
  });

  test('控制器：上传和项目文件分开发', () async {
    final socket = FakeSocket();
    final c = ProviderContainer(overrides: [
      chatSocketProvider.overrideWithValue(socket),
      apiProvider.overrideWithValue(_Api()),
      cacheStoreProvider.overrideWithValue(MemoryCacheStore()),
    ]);
    addTearDown(c.dispose);
    final sub = c.listen(chatProvider('p1'), (_, _) {});
    addTearDown(sub.close);
    await Future<void>.delayed(Duration.zero);
    c.read(chatProvider('p1').notifier).send('看看', files: const [
      FileBlock(source: 'upload', id: 'u1', name: 'a.txt', mime: 'text/plain', size: 1),
      FileBlock(source: 'project', id: 'notes/大纲.md', name: '大纲.md', mime: 'text/markdown', size: 2, projectId: 'p1'),
    ]);
    final e = socket.sent.single;
    expect(e['project_id'], 'p1');
    expect(e['attachments'], ['u1']);
    expect(e['project_files'], ['notes/大纲.md']);
  });

  testWidgets('主聊天：添加附件里是“我的文件”（个人工作区，v1.21），选择器读 /api/projects/me/files', (tester) async {
    final sent = await _pump(tester);
    await tester.tap(find.byTooltip('添加附件'));
    await _settle(tester);
    expect(find.text('相册'), findsOneWidget);
    expect(find.text('项目文件'), findsNothing);
    await tester.tap(find.text('我的文件'));
    await _settle(tester);
    expect(find.text('引用我的文件'), findsOneWidget);
    await tester.tap(find.text('结果.csv'));
    await _settle(tester);
    await tester.tap(find.text('引用 1 个文件'));
    await _settle(tester);
    expect(find.textContaining('我的文件 · '), findsOneWidget);
    await tester.tap(find.byIcon(Icons.arrow_upward_rounded));
    await _settle(tester);
    expect(sent.single.projectId, 'me');
    expect(sent.single.id, '结果.csv');
  });

  testWidgets('没有工作区（首页快捷输入框）：没有引用文件这个来源', (tester) async {
    await _pump(tester, projectId: null);
    await tester.tap(find.byTooltip('添加附件'));
    await _settle(tester);
    expect(find.text('我的文件'), findsNothing);
    expect(find.text('项目文件'), findsNothing);
  });

  testWidgets('项目对话：选两个文件 → 托盘里是引用 → 发出 source=project；再选时已选的不能重复', (tester) async {
    final sent = await _pump(tester, projectId: 'p1');
    await tester.tap(find.byTooltip('添加附件'));
    await _settle(tester);
    await tester.tap(find.text('项目文件'));
    await _settle(tester);
    expect(find.text('引用项目文件'), findsOneWidget);
    expect(find.text('选几个文件'), findsOneWidget);
    await tester.tap(find.text('大纲.md'));
    expect(find.textContaining('notes · 2 KB'), findsOneWidget); // 标题是文件名，文件夹进副标题（v1.14）
    await tester.tap(find.text('照片.png'));
    await _settle(tester);
    expect(find.text('已选 2'), findsOneWidget);
    await tester.tap(find.text('照片.png')); // 再点取消
    await _settle(tester);
    await tester.tap(find.text('照片.png'));
    await _settle(tester);
    await tester.tap(find.text('引用 2 个文件'));
    await _settle(tester);
    expect(find.text('引用项目文件'), findsNothing);
    expect(find.byIcon(Icons.folder_rounded), findsNWidgets(2)); // 托盘名片角标上的文件夹记号
    expect(find.textContaining('项目文件 · '), findsNWidgets(2)); // 名片第二行（v1.14）

    // 再打开：已在托盘里的两项不可选
    await tester.tap(find.byTooltip('添加附件'));
    await _settle(tester);
    await tester.tap(find.text('项目文件'));
    await _settle(tester);
    expect(find.text('已在这条消息里'), findsNWidgets(2));
    await tester.tap(find.text('照片.png').last); // 托盘名片里也有这个名字；弹层在上面
    await _settle(tester);
    expect(find.text('选几个文件'), findsOneWidget);
    await tester.tapAt(const Offset(200, 20)); // 点遮罩关掉
    await _settle(tester);

    await tester.tap(find.bySemanticsLabel('发送'));
    await _settle(tester);
    expect([for (final f in sent) (f.source, f.id)], [('project', 'notes/大纲.md'), ('project', '照片.png')]);
  });

  testWidgets('附件弹层高度随内容（v2.97）：手机含状态栏 / 手势条，弹层只有一排来源那么高，不撑满全屏', (tester) async {
    for (final pid in ['me', null]) {
      await _pump(tester, projectId: pid);
      tester.view.physicalSize = const Size(1080, 2340);
      tester.view.devicePixelRatio = 2.75;
      tester.view.padding = const FakeViewPadding(top: 120, bottom: 63);
      await _settle(tester);
      await tester.tap(find.byTooltip('添加附件'));
      await _settle(tester);
      final sheet = tester.getRect(find.byType(GlassSheet));
      final label = tester.getRect(find.text('相册'));
      final screen = tester.view.physicalSize / tester.view.devicePixelRatio;
      expect(sheet.height, lessThan(screen.height * 0.3), reason: 'pid=$pid 弹层 ${sheet.height} / 屏 ${screen.height}');
      // 标签下面只剩内边距 + 手势条安全区，没有一大片空白
      expect(sheet.bottom - label.bottom, lessThan(16 + 63 / 2.75 + 8));
      await tester.tapAt(const Offset(10, 10));
      await _settle(tester);
    }
  });
}
