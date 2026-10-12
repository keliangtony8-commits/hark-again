// 把回复存成项目文件（v1.15）：回复操作行多一颗“存到项目文件”（有内容且 ChatView 给了才有）；
// 项目对话直接存进本项目，主聊天先选项目（最近活跃的在前）；存好提示“已存进「项目」· 文件名”；没有项目 / 出错给提示。
import 'package:assistant/core/api.dart';
import 'package:assistant/core/cache.dart';
import 'package:assistant/features/chat/message_view.dart';
import 'package:assistant/features/projects/save_reply.dart';
import 'package:assistant/models/block.dart';
import 'package:assistant/models/message.dart';
import 'package:assistant/models/resources.dart';
import 'package:assistant/theme/app_theme.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

class _Api implements Api {
  _Api({this.projects = const []});
  final List<Map<String, dynamic>> projects;
  final posts = <(String, Object?)>[];

  @override
  Future<dynamic> get(String path) async => path == '/api/projects' ? projects : <dynamic>[];

  @override
  Future<dynamic> post(String path, [Object? body]) async {
    posts.add((path, body));
    final pid = (body as Map)['project_id'];
    if (pid == 'bad') throw ApiError('项目不存在', 404);
    final name = projects.firstWhere((p) => p['id'] == pid, orElse: () => {'name': '考研'})['name'];
    return {'project_id': pid, 'project_name': name, 'path': '复习计划.md', 'name': '复习计划.md', 'size': 10, 'mime': 'text/markdown'};
  }

  @override
  dynamic noSuchMethod(Invocation i) => throw UnimplementedError();
}

Map<String, dynamic> _p(String id, String name, String? active) =>
    {'id': id, 'name': name, 'emoji': '📁', 'rules': '', 'last_active_at': active};

Future<void> _settle(WidgetTester tester) async {
  for (var i = 0; i < 10; i++) {
    await tester.pump(const Duration(milliseconds: 100));
  }
}

Future<void> _pump(WidgetTester tester, _Api api, {String projectId = ''}) async {
  tester.view.physicalSize = const Size(400, 800);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(ProviderScope(
    overrides: [apiProvider.overrideWithValue(api), cacheStoreProvider.overrideWithValue(MemoryCacheStore())],
    child: MaterialApp(
      theme: buildTheme(Brightness.light),
      home: Scaffold(
        body: Consumer(
          builder: (context, ref, _) => MessageView(
            const Message(id: 'm1', role: 'assistant', blocks: [TextBlock('# 复习计划\n先看线代')]),
            last: true,
            onSave: () => saveReplyToProject(context, ref, messageId: 'm1', projectId: projectId),
          ),
        ),
      ),
    ),
  ));
  await _settle(tester);
}

void main() {
  test('选项目的顺序：最近活跃在前，没有时间的排后', () {
    final list = saveTargets([
      Project.fromJson(_p('a', '旧', '2026-10-01T00:00:00Z')),
      Project.fromJson(_p('b', '无', null)),
      Project.fromJson(_p('c', '新', '2026-10-11T00:00:00Z')),
    ]);
    expect(list.map((p) => p.id), ['c', 'a', 'b']);
    expect(savedReplyText('考研', '复习计划.md'), '已存进「考研」· 复习计划.md');
  });

  testWidgets('没给 onSave 就没有这颗键', (tester) async {
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    await tester.pumpWidget(ProviderScope(
      child: MaterialApp(
        theme: buildTheme(Brightness.light),
        home: const Scaffold(body: MessageView(Message(id: 'm1', role: 'assistant', blocks: [TextBlock('好')]), last: true)),
      ),
    ));
    await tester.pump(const Duration(seconds: 1));
    expect(find.byTooltip('复制'), findsOneWidget);
    expect(find.byTooltip(saveReplyLabel), findsNothing);
  });

  testWidgets('项目对话：一点就存进本项目，不弹选择', (tester) async {
    final api = _Api();
    await _pump(tester, api, projectId: 'p1');
    await tester.tap(find.byTooltip(saveReplyLabel));
    await _settle(tester);
    expect(api.posts.single.$1, '/api/messages/m1/save-to-project');
    expect(api.posts.single.$2, {'project_id': 'p1'});
    expect(find.text('存到哪个项目'), findsNothing);
    expect(find.text('已存进「考研」· 复习计划.md'), findsOneWidget);
  });

  testWidgets('主聊天：先选项目（最近的在前），选了才存', (tester) async {
    final api = _Api(projects: [_p('p1', '考研', '2026-10-01T00:00:00Z'), _p('p2', '旅行', '2026-10-11T00:00:00Z')]);
    await _pump(tester, api);
    await tester.tap(find.byTooltip(saveReplyLabel));
    await _settle(tester);
    expect(find.text('存到哪个项目'), findsOneWidget);
    expect(tester.getTopLeft(find.text('旅行')).dy, lessThan(tester.getTopLeft(find.text('考研')).dy));
    expect(api.posts, isEmpty);
    await tester.tap(find.text('旅行'));
    await _settle(tester);
    expect(api.posts.single.$2, {'project_id': 'p2'});
    expect(find.text('已存进「旅行」· 复习计划.md'), findsOneWidget);
  });

  testWidgets('主聊天：还没有项目 → 提示先建一个', (tester) async {
    final api = _Api();
    await _pump(tester, api);
    await tester.tap(find.byTooltip(saveReplyLabel));
    await _settle(tester);
    expect(api.posts, isEmpty);
    expect(find.text('还没有项目，先在“项目”里建一个'), findsOneWidget);
  });

  testWidgets('服务器拒绝 → 提示原因', (tester) async {
    final api = _Api();
    await _pump(tester, api, projectId: 'bad');
    await tester.tap(find.byTooltip(saveReplyLabel));
    await _settle(tester);
    expect(find.text('项目不存在'), findsOneWidget);
  });
}
