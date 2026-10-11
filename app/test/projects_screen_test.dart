// 项目列表（v0.73）：页头“N 个项目 · 最近 …” + 衬线大标题；按最近活动排序；
// 卡片 ⋯ 菜单：编辑名称和图标（只 PATCH 改过的字段，没改不发请求）、删除（先确认，确认后 DELETE 并从列表消失）；
// 加载中是和卡片同高的骨架；新建表单的图标选择会带进 POST。
import 'package:assistant/app.dart';
import 'package:assistant/core/api.dart';
import 'package:assistant/core/cache.dart';
import 'package:assistant/core/chat_socket.dart';
import 'package:assistant/core/session.dart';
import 'package:assistant/features/projects/project_form.dart';
import 'package:assistant/features/projects/project_home.dart';
import 'package:assistant/features/projects/projects_screen.dart';
import 'package:assistant/models/resources.dart';
import 'package:assistant/ui/motion.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'chat_controller_test.dart' show FakeSocket;

class _SignedIn extends SessionNotifier {
  @override
  Future<Session> build() async => const Session(server: 'http://x', token: 't');
}

class _Api implements Api {
  final now = DateTime.now();
  late final projects = <Map<String, dynamic>>[
    {'id': 'p1', 'name': '考研', 'emoji': '📚', 'rules': '回答用中文', 'conversation_count': 3, 'last_active_at': now.subtract(const Duration(days: 3)).toIso8601String()},
    {'id': 'p2', 'name': '找实习', 'emoji': '💼', 'rules': '', 'conversation_count': 0, 'last_active_at': now.subtract(const Duration(minutes: 5)).toIso8601String()},
  ];
  late final convs = <Map<String, dynamic>>[
    {'id': 'c1', 'title': '真题第一轮', 'updated_at': now.subtract(const Duration(days: 2)).toIso8601String()},
    {'id': 'c2', 'title': '单词计划', 'updated_at': now.subtract(const Duration(hours: 1)).toIso8601String()},
    {'id': 'c3', 'title': '择校', 'pinned': true, 'updated_at': now.subtract(const Duration(days: 9)).toIso8601String()},
    {'id': 'c4', 'title': '政治大纲', 'updated_at': now.subtract(const Duration(days: 4)).toIso8601String()},
  ];
  int sec(Duration d) => now.subtract(d).millisecondsSinceEpoch ~/ 1000;
  late var files = <Map<String, dynamic>>[
    {'path': 'notes/大纲.md', 'name': '大纲.md', 'size': 2048, 'mime': 'text/markdown', 'modified': sec(const Duration(hours: 2))},
    {'path': '真题 2024.pdf', 'name': '真题 2024.pdf', 'size': 3 << 20, 'mime': 'application/pdf', 'modified': sec(const Duration(minutes: 10))},
    {'path': '旧计划.txt', 'name': '旧计划.txt', 'size': 100, 'mime': 'text/plain', 'modified': sec(const Duration(days: 30))},
    {'path': '词表.csv', 'name': '词表.csv', 'size': 900, 'mime': 'text/csv', 'modified': sec(const Duration(days: 1))},
    {'path': '照片.png', 'name': '照片.png', 'size': 5000, 'mime': 'image/png', 'modified': sec(const Duration(days: 20))},
  ];
  final calls = <String>[];
  final bodies = <Object?>[];

  @override
  Future<dynamic> get(String path) async {
    if (path == '/api/inbox') return {'unread': 0, 'latest': null};
    if (path == '/api/projects') return [...projects];
    if (path == '/api/conversations?project_id=p1') return [...convs];
    if (path == '/api/projects/p1/files') return [...files];
    if (path.startsWith('/api/conversations/')) {
      final id = path.split('/').last;
      return {'id': id, 'title': id, 'messages': [{'id': 'm-$id', 'role': 'user', 'blocks': [{'type': 'text', 'text': '续聊 $id'}]}]};
    }
    return <dynamic>[];
  }

  @override
  Future<dynamic> post(String path, [Object? body]) async {
    calls.add('POST $path');
    bodies.add(body);
    final p = {'id': 'p3', 'rules': '', ...(body as Map).cast<String, dynamic>()};
    projects.add(p);
    return p;
  }

  @override
  Future<dynamic> patch(String path, [Object? body]) async {
    calls.add('PATCH $path');
    bodies.add(body);
    final i = projects.indexWhere((p) => path.endsWith('/${p['id']}'));
    projects[i] = {...projects[i], ...(body as Map).cast<String, dynamic>()};
    return projects[i];
  }

  @override
  Future<dynamic> delete(String path) async {
    calls.add('DELETE $path');
    projects.removeWhere((p) => path.endsWith('/${p['id']}'));
    return null;
  }

  @override
  dynamic noSuchMethod(Invocation i) => throw UnimplementedError();
}

Future<void> _settle(WidgetTester tester) async {
  for (var i = 0; i < 12; i++) {
    await tester.pump(const Duration(milliseconds: 100));
  }
}

Future<_Api> _pump(WidgetTester tester, {String at = '/projects', List<Map<String, dynamic>>? files}) async {
  tester.view.physicalSize = const Size(400, 860);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  SharedPreferences.setMockInitialValues({});
  final api = _Api();
  if (files != null) api.files = files;
  final container = ProviderContainer(overrides: [
    sessionProvider.overrideWith(_SignedIn.new),
    apiProvider.overrideWithValue(api),
    chatSocketProvider.overrideWithValue(FakeSocket()),
    cacheStoreProvider.overrideWithValue(MemoryCacheStore()),
  ]);
  addTearDown(container.dispose);
  await tester.pumpWidget(UncontrolledProviderScope(container: container, child: const AssistantApp()));
  await _settle(tester);
  container.read(routerProvider).go('/projects');
  await _settle(tester);
  if (at != '/projects') {
    container.read(routerProvider).push(at);
    await _settle(tester);
  }
  return api;
}

Finder _menuOf(String name) => find.descendant(
      of: find.ancestor(of: find.text(name), matching: find.byType(Pressable)).first,
      matching: find.byTooltip('更多'),
    );

void main() {
  test('byActivity：最近活动在前，没有时间的排最后', () {
    final a = Project.fromJson({'id': 'a', 'name': 'a', 'last_active_at': '2026-10-01T00:00:00Z'});
    final b = Project.fromJson({'id': 'b', 'name': 'b', 'last_active_at': '2026-10-10T00:00:00Z'});
    final c = Project.fromJson({'id': 'c', 'name': 'c'});
    expect(byActivity([a, c, b]).map((p) => p.id), ['b', 'a', 'c']);
  });

  testWidgets('页头摘要 + 按最近活动排序', (tester) async {
    await _pump(tester);
    expect(find.text('2 个项目 · 最近 5 分钟前'), findsOneWidget);
    expect(find.text('项目'), findsWidgets); // 顶栏标签 + 衬线大标题
    final y1 = tester.getTopLeft(find.text('找实习')).dy;
    final y2 = tester.getTopLeft(find.text('考研')).dy;
    expect(y1, lessThan(y2), reason: '刚动过的“找实习”排在前面');
    expect(find.text('3 个对话 · 更新于 3 天前'), findsOneWidget);
  });

  testWidgets('⋯ 菜单编辑：只发改过的字段；什么都没改不发请求', (tester) async {
    final api = await _pump(tester);
    await tester.tap(_menuOf('考研'));
    await _settle(tester);
    await tester.tap(find.text('编辑名称和图标'));
    await _settle(tester);
    expect(find.text('编辑项目'), findsOneWidget);
    await tester.tap(find.text('保存'));
    await _settle(tester);
    expect(api.calls.where((c) => c.startsWith('PATCH')), isEmpty);

    await tester.tap(_menuOf('考研'));
    await _settle(tester);
    await tester.tap(find.text('编辑名称和图标'));
    await _settle(tester);
    await tester.tap(find.text('🎯'));
    await tester.pump();
    await tester.tap(find.text('保存'));
    await _settle(tester);
    expect(api.calls.last, 'PATCH /api/projects/p1');
    expect(api.bodies.last, {'emoji': '🎯'});
    expect(find.text('🎯'), findsOneWidget);
  });

  testWidgets('⋯ 菜单删除：取消不删，确认后 DELETE 并从列表消失', (tester) async {
    final api = await _pump(tester);
    await tester.tap(_menuOf('找实习'));
    await _settle(tester);
    await tester.tap(find.text('删除项目'));
    await _settle(tester);
    expect(find.text('删除“找实习”？'), findsOneWidget);
    await tester.tap(find.text('取消'));
    await _settle(tester);
    expect(api.calls, isEmpty);

    await tester.tap(_menuOf('找实习'));
    await _settle(tester);
    await tester.tap(find.text('删除项目'));
    await _settle(tester);
    await tester.tap(find.text('删除'));
    await _settle(tester);
    expect(api.calls, ['DELETE /api/projects/p2']);
    expect(find.text('找实习'), findsNothing);
    expect(find.text('1 个项目 · 最近 3 天前'), findsOneWidget);
  });

  testWidgets('新建：选的图标带进 POST，然后进入项目', (tester) async {
    final api = await _pump(tester);
    await tester.tap(find.byTooltip('新项目'));
    await _settle(tester);
    await tester.enterText(find.widgetWithText(TextField, '名称'), '旅行');
    await tester.tap(find.text('✈️'));
    await tester.pump();
    await tester.tap(find.text('创建'));
    await _settle(tester);
    expect(api.bodies.last, {'name': '旅行', 'emoji': '✈️'});
    expect(projectEmojis, contains('✈️'));
  });

  test('projectRecent：置顶在前，再按更新新→旧，最多 3 条；projectLine 规则 > 档案 > 引导', () {
    ConversationSummary c(String id, {int? daysAgo, bool pinned = false}) => ConversationSummary(
        id: id, title: id, pinned: pinned, updatedAt: daysAgo == null ? null : DateTime(2026, 10, 12).subtract(Duration(days: daysAgo)));
    final list = [c('old', daysAgo: 9), c('none'), c('new', daysAgo: 0), c('pin', daysAgo: 30, pinned: true), c('mid', daysAgo: 3)];
    expect(projectRecent(list).map((e) => e.id), ['pin', 'new', 'mid']);
    expect(projectRecent(list, max: 9).map((e) => e.id), ['pin', 'new', 'mid', 'old', 'none']);
    expect(projectLine(Project.fromJson({'id': 'a', 'rules': '回答用中文\n第二行', 'brief': '# 档案\n目标 985'})), '回答用中文');
    expect(projectLine(Project.fromJson({'id': 'a', 'brief': '# 档案\n- 目标 985'})), '目标 985');
    expect(projectLine(Project.fromJson({'id': 'a'})), startsWith('还没有规则和档案'));
  });

  testWidgets('项目内：标题栏只有“项目对话”和 ⋯；首屏有名字、规则、最近 3 条对话和起步建议', (tester) async {
    await _pump(tester, at: '/projects/p1');
    expect(find.byTooltip('项目对话'), findsOneWidget);
    expect(find.byTooltip('项目菜单'), findsOneWidget);
    expect(find.byTooltip('项目文件'), findsNothing);
    expect(find.byTooltip('编辑项目'), findsNothing);
    expect(find.text('今天想做点什么？'), findsNothing);
    expect(find.byType(ProjectHome), findsOneWidget);
    expect(find.text('回答用中文'), findsOneWidget);
    expect(find.text('最近的对话'), findsOneWidget);
    expect(find.text('全部 4 个'), findsOneWidget);
    final ys = [for (final t in ['择校', '单词计划', '真题第一轮']) tester.getTopLeft(find.text(t)).dy];
    expect(ys, orderedEquals([...ys]..sort()));
    expect(find.text('政治大纲'), findsNothing);
    await tester.drag(find.byType(ProjectHome), const Offset(0, -400));
    await _settle(tester);
    expect(find.text('或者新开一段'), findsOneWidget);
    expect(find.text('总结一下这个项目现在的进度'), findsOneWidget);
  });

  testWidgets('项目首屏：点最近对话 → 打开续聊；⋯ 菜单 = 列表同一份', (tester) async {
    await _pump(tester, at: '/projects/p1');
    await tester.tap(find.text('单词计划'));
    await _settle(tester);
    expect(find.text('续聊 c2'), findsOneWidget);
    expect(find.byType(ProjectHome), findsNothing);
    await tester.tap(find.byTooltip('项目菜单'));
    await _settle(tester);
    for (final t in ['编辑名称和图标', '规则与档案', '项目文件', '删除项目']) {
      expect(find.text(t), findsOneWidget);
    }
  });

  testWidgets('项目内删除：确认后退回列表', (tester) async {
    final api = await _pump(tester, at: '/projects/p1');
    await tester.tap(find.byTooltip('项目菜单'));
    await _settle(tester);
    await tester.tap(find.text('删除项目'));
    await _settle(tester);
    await tester.tap(find.text('删除'));
    await _settle(tester);
    expect(api.calls, ['DELETE /api/projects/p1']);
    expect(find.byType(ProjectHome), findsNothing);
    expect(find.text('1 个项目 · 最近 5 分钟前'), findsOneWidget);
  });

  test('projectRecentFiles：按修改时间新→旧，没时间排后；projectFileLine 带文件夹', () {
    ProjectFile f(String p, int? t) => ProjectFile.fromJson({'path': p, 'name': p.split('/').last, 'size': 2048, 'mime': 'text/plain', 'modified': t});
    final list = [f('a', 100), f('b', null), f('c', 300), f('d', 200), f('e', 50)];
    expect(projectRecentFiles(list).map((x) => x.path), ['c', 'd', 'a']);
    expect(projectRecentFiles([f('b', null), f('x', null)], max: 5).map((x) => x.path), ['b', 'x']);
    expect(projectFileLine(f('notes/sub/大纲.md', 1)), 'notes/sub · 2 KB');
    expect(projectFileLine(f('大纲.md', 1)), '2 KB');
    expect(ProjectFile.fromJson({'path': 'a', 'modified': 1.5}).modified, DateTime.fromMillisecondsSinceEpoch(1500));
  });

  testWidgets('项目首屏“文件”：最近改过的 3 个，全部 5 个 → 文件抽屉', (tester) async {
    await _pump(tester, at: '/projects/p1');
    await tester.drag(find.byType(ProjectHome), const Offset(0, -300));
    await _settle(tester);
    expect(find.text('文件'), findsOneWidget);
    final ys = [for (final t in ['真题 2024.pdf', '大纲.md', '词表.csv']) tester.getTopLeft(find.text(t)).dy];
    expect(ys, orderedEquals([...ys]..sort()));
    expect(find.text('旧计划.txt'), findsNothing);
    expect(find.text('notes · 2 KB'), findsOneWidget);
    await tester.tap(find.text('全部 5 个'));
    await _settle(tester);
    expect(find.text('项目文件'), findsOneWidget);
    expect(find.text('旧计划.txt'), findsOneWidget);
  });

  testWidgets('项目首屏“文件”：空文件夹给一行上传入口', (tester) async {
    await _pump(tester, at: '/projects/p1', files: []);
    await tester.drag(find.byType(ProjectHome), const Offset(0, -300));
    await _settle(tester);
    expect(find.text('放点资料进来'), findsOneWidget);
    expect(find.text('管理'), findsNothing);
    await tester.tap(find.text('放点资料进来'));
    await _settle(tester);
    expect(find.text('文件夹是空的'), findsOneWidget);
  });
}
