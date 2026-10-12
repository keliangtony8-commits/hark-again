// 本对话全部文件（v1.33）：models/conversation_files.dart 规则 + ConversationFilesSheet（列表、筛选、不在了的行、打包按钮、空态、出错）。
import 'package:assistant/core/api.dart';
import 'package:assistant/features/chat/conversation_files.dart';
import 'package:assistant/models/conversation_files.dart';
import 'package:assistant/theme/app_theme.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

Map<String, dynamic> _f(String name, String origin, {String source = 'project', String id = '', int size = 2048, bool gone = false}) => {
      'key': '$source:me:${id.isEmpty ? name : id}',
      'name': name,
      'mime': name.endsWith('.pdf') ? 'application/pdf' : 'text/markdown',
      'size': size,
      'source': source,
      'id': id.isEmpty ? name : id,
      'project_id': source == 'project' ? 'me' : null,
      'origin': origin,
      'message_id': 'm1',
      'at': '2026-10-12T07:00:00+00:00',
      'gone': gone,
    };

Map<String, dynamic> _body() => {
      'count': 4,
      'available': 3,
      'size': 6144,
      'zip_max': 200 * 1024 * 1024,
      'files': [
        _f('报告.pdf', 'delivered', source: 'upload', id: 'u1'),
        _f('发票.pdf', 'downloaded', id: 'downloads/发票.pdf', gone: true),
        _f('总结.md', 'written', id: 'out/总结.md'),
        _f('需求.pdf', 'sent', source: 'upload', id: 'u2'),
      ],
    };

class _Api implements Api {
  _Api(this.body, {this.fail = false});
  Map<String, dynamic> body;
  bool fail;
  final calls = <String>[];
  @override
  Future<dynamic> get(String path) async {
    calls.add('GET $path');
    if (fail) throw ApiError('服务器连不上', 503);
    return body;
  }

  @override
  String fileUrl(String path) => '$path?token=t';

  @override
  dynamic noSuchMethod(Invocation i) => throw UnimplementedError();
}

Future<void> _settle(WidgetTester tester) async {
  for (var i = 0; i < 12; i++) {
    await tester.pump(const Duration(milliseconds: 100));
  }
}

Future<_Api> _pump(WidgetTester tester, _Api api) async {
  tester.view.physicalSize = const Size(400, 800);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(ProviderScope(
    retry: (_, _) => null, // 出错直接显示，不等自动重试
    overrides: [apiProvider.overrideWithValue(api)],
    child: MaterialApp(
      theme: buildTheme(Brightness.light),
      home: const Scaffold(body: Column(mainAxisSize: MainAxisSize.min, children: [ConversationFilesSheet(id: 'c1')])),
    ),
  ));
  await _settle(tester);
  return api;
}

void main() {
  test('规则：来源叫法、副标题、下载路径、来源统计、打包能不能点', () {
    final d = ConversationFiles.fromJson(_body());
    final [pdf, gone, md, sent] = d.files;
    expect(conversationFileLine(pdf), '交给你的 · PDF 文档 · 2 KB');
    expect(conversationFileLine(gone), '网页下载 · 已从工作区删除或挪走');
    expect(conversationFilePath(pdf), '/api/uploads/u1');
    expect(conversationFilePath(md), '/api/projects/me/files/out/%E6%80%BB%E7%BB%93.md');
    expect(fileOriginLabel(sent.origin), '你发的');
    expect(d.origins, [('delivered', 1), ('sent', 1), ('downloaded', 1), ('written', 1)]);
    expect(d.canZip, isTrue);
    expect(d.zipNote, '3 个文件 · 6 KB');
    final big = ConversationFiles.fromJson({..._body(), 'size': 300 * 1024 * 1024});
    expect(big.canZip, isFalse);
    expect(big.zipNote, contains('超过打包上限'));
    expect(ConversationFiles.fromJson({..._body(), 'available': 0}).zipNote, contains('都已经不在'));
    expect(ConversationFiles.fromJson({'files': []}).files, isEmpty);
    expect(conversationFileSemantics(gone), contains('已不在，打不开'));
    expect(conversationZipPath('c1'), '/api/conversations/c1/files.zip');
  });

  testWidgets('弹层：列表、筛选、不在了的行、打包按钮', (tester) async {
    final api = await _pump(tester, _Api(_body()));
    expect(api.calls, ['GET /api/conversations/c1/files']);
    expect(find.text('本对话全部文件'), findsOneWidget);
    expect(find.text('3 个文件 · 6 KB'), findsOneWidget);
    expect(find.text('报告.pdf'), findsOneWidget);
    expect(find.textContaining('已不在', findRichText: true), findsOneWidget);
    final zip = tester.widget<TextButton>(find.ancestor(of: find.text('打包下载'), matching: find.byType(TextButton)));
    expect(zip.onPressed, isNotNull);
    // 筛选：只看“助手写的”（第 5 个，横向滚动条里先滚出来）
    await tester.ensureVisible(find.text('助手写的 1'));
    await _settle(tester);
    await tester.tap(find.text('助手写的 1'));
    await _settle(tester);
    expect(find.text('总结.md'), findsOneWidget);
    expect(find.text('报告.pdf'), findsNothing);
    // 再点一次 = 回到全部
    await tester.tap(find.text('助手写的 1'));
    await _settle(tester);
    expect(find.text('报告.pdf'), findsOneWidget);
  });

  testWidgets('超过打包上限：按钮不能点、说明原因', (tester) async {
    await _pump(tester, _Api({..._body(), 'size': 300 * 1024 * 1024}));
    final zip = tester.widget<TextButton>(find.ancestor(of: find.text('打包下载'), matching: find.byType(TextButton)));
    expect(zip.onPressed, isNull);
    expect(find.textContaining('超过打包上限'), findsOneWidget);
  });

  testWidgets('只有一种来源：不显示筛选条', (tester) async {
    await _pump(tester, _Api({..._body(), 'files': [_f('a.md', 'written')], 'available': 1}));
    expect(find.byType(ChoiceChip), findsNothing);
    expect(find.text('a.md'), findsOneWidget);
  });

  testWidgets('空对话：说明 + 没有打包按钮', (tester) async {
    await _pump(tester, _Api({'count': 0, 'available': 0, 'size': 0, 'files': []}));
    expect(find.text('这个对话还没有文件'), findsOneWidget);
    expect(find.text('打包下载'), findsNothing);
  });

  testWidgets('出错：显示原因和重试', (tester) async {
    await _pump(tester, _Api(_body(), fail: true));
    expect(find.text('加载失败'), findsOneWidget);
    expect(find.text('重试'), findsOneWidget);
  });
}
