// 项目页（v2.93 §Q 按 Hark）：列表 = 页头“N 个项目 · 最近 …” + 一行一个大字项目名，按最近活动排序，行尾项目汇总状态胶囊，
// 不是当前的项目变灰（projectIsCurrent）、没有输入框；⋯ 菜单：编辑（只 PATCH 改过的字段）、删除（先确认）、电脑；
// 进项目仍在一级外壳下（顶栏在），左上 + → ≡ 同一颗钮，header 行 ‹ 返回列表；项目首屏只列本项目对话。
import 'package:assistant/app.dart';
import 'package:assistant/core/api.dart';
import 'package:assistant/core/cache.dart';
import 'package:assistant/core/chat_socket.dart';
import 'package:assistant/core/session.dart';
import 'package:assistant/features/chat/title_pill.dart';
import 'package:assistant/features/projects/project_files_sheet.dart' show projectFileLine;
import 'package:assistant/features/projects/project_form.dart';
import 'package:assistant/features/projects/project_home.dart';
import 'package:assistant/features/projects/projects_screen.dart';
import 'package:assistant/models/resources.dart';
import 'package:assistant/theme/app_theme.dart';
import 'package:assistant/theme/tokens.dart';
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
    {'id': 'p1', 'name': '考研', 'emoji': '📚', 'rules': '回答用中文', 'conversation_count': 3, 'status': 'done', 'last_active_at': now.subtract(const Duration(days: 3)).toIso8601String()},
    {'id': 'p2', 'name': '找实习', 'emoji': '💼', 'rules': '', 'conversation_count': 0, 'last_active_at': now.subtract(const Duration(minutes: 5)).toIso8601String()},
  ];
  late final convs = <Map<String, dynamic>>[
    {'id': 'c1', 'title': '真题第一轮', 'updated_at': now.subtract(const Duration(days: 2)).toIso8601String()},
    {'id': 'c2', 'title': '单词计划', 'status': 'running', 'updated_at': now.subtract(const Duration(hours: 1)).toIso8601String()},
    {'id': 'c3', 'title': '择校', 'status': 'waiting', 'pinned': true, 'updated_at': now.subtract(const Duration(days: 9)).toIso8601String()},
    {'id': 'c4', 'title': '政治大纲', 'updated_at': now.subtract(const Duration(days: 4)).toIso8601String()},
  ];
  final calls = <String>[];
  final bodies = <Object?>[];

  @override
  Future<dynamic> get(String path) async {
    if (path == '/api/inbox') return {'unread': 0, 'latest': null};
    if (path == '/api/projects') return [...projects];
    if (path == '/api/conversations?project_id=p1') return [...convs];
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

Future<_Api> _pump(WidgetTester tester, {String at = '/projects'}) async {
  tester.view.physicalSize = const Size(400, 860);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  SharedPreferences.setMockInitialValues({});
  final api = _Api();
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

Color? _colorOf(WidgetTester tester, String text) => tester.widget<Text>(find.text(text)).style?.color;

void main() {
  test('byActivity：最近活动在前，没有时间的排最后', () {
    final a = Project.fromJson({'id': 'a', 'name': 'a', 'last_active_at': '2026-10-01T08:00:00+08:00'});
    final b = Project.fromJson({'id': 'b', 'name': 'b', 'last_active_at': '2026-10-10T08:00:00+08:00'});
    final c = Project.fromJson({'id': 'c', 'name': 'c'});
    expect(byActivity([a, c, b]).map((p) => p.id), ['b', 'a', 'c']);
  });

  test('v2.93 projectIsCurrent：第一个、进行中、等你回复用正文色；已完成和其余变灰；status 解析', () {
    Project p(String? st) => Project.fromJson({'id': 'x', 'status': st});
    expect(projectIsCurrent(0, p(null)), isTrue);
    expect(projectIsCurrent(0, p('done')), isTrue);
    expect(projectIsCurrent(3, p('running')), isTrue);
    expect(projectIsCurrent(3, p('waiting')), isTrue);
    expect(projectIsCurrent(1, p('done')), isFalse);
    expect(projectIsCurrent(1, p(null)), isFalse);
    expect(p('waiting').status, ConversationStatus.waiting);
    expect(p('weird').status, isNull);
  });

  testWidgets('列表：页头摘要、大字名按最近活动排序、汇总状态胶囊、不是当前的变灰、没有输入框', (tester) async {
    await _pump(tester);
    expect(find.text('2 个项目 · 最近 5 分钟前'), findsOneWidget);
    expect(find.text('项目'), findsOneWidget); // 只有顶栏分段，不再画大标题
    final y1 = tester.getTopLeft(find.text('找实习')).dy;
    final y2 = tester.getTopLeft(find.text('考研')).dy;
    expect(y1, lessThan(y2), reason: '刚动过的“找实习”排在前面');
    expect(find.text('已完成'), findsOneWidget); // 考研的汇总状态
    final ctx = tester.element(find.text('考研'));
    expect(_colorOf(tester, '找实习'), ctx.palette.text);
    expect(_colorOf(tester, '考研'), ctx.palette.text3, reason: '已完成且不是最近的：变灰');
    expect(find.byType(TextField), findsNothing, reason: '项目列表不放输入框');
    expect(tester.widget<MenuPlusIcon>(find.byType(MenuPlusIcon)).plus, isTrue);
  });

  testWidgets('进项目：顶栏仍在，左上 + 转成 ≡（同一颗钮）；header 行 ‹ 返回列表，钮转回 +', (tester) async {
    await _pump(tester);
    await tester.tap(find.text('考研'));
    await _settle(tester);
    expect(find.byType(ProjectHome), findsOneWidget);
    expect(find.text('主页'), findsOneWidget, reason: '一级外壳顶栏不淡出');
    expect(find.byTooltip('我的'), findsOneWidget);
    expect(tester.widget<MenuPlusIcon>(find.byType(MenuPlusIcon).last).plus, isFalse);
    expect(find.byTooltip('项目对话'), findsOneWidget);
    await tester.tap(find.byTooltip('返回项目列表'));
    await _settle(tester);
    expect(find.byType(ProjectHome), findsNothing);
    expect(find.text('2 个项目 · 最近 5 分钟前'), findsOneWidget);
    expect(tester.widget<MenuPlusIcon>(find.byType(MenuPlusIcon)).plus, isTrue);
  });

  testWidgets('切页途中：钮停在原地，按路由进度从 + 画到 ≡（Hero 飞行）', (tester) async {
    await _pump(tester);
    final before = tester.getCenter(find.byTooltip('新项目'));
    await tester.tap(find.text('考研'));
    await tester.pump();
    await tester.pump(Motion.morph ~/ 2);
    final glyphs = tester.widgetList<MenuPlusGlyph>(find.byType(MenuPlusGlyph)).map((g) => g.t).toList();
    expect(glyphs.any((t) => t > 0.01 && t < 0.99), isTrue, reason: '飞行中是半路形状：$glyphs');
    await _settle(tester);
    expect(tester.getCenter(find.byTooltip('项目对话')), before);
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

  test('projectConversations：置顶在前，再按更新新→旧，不截断；projectFileLine 带文件夹', () {
    ConversationSummary c(String id, {int? daysAgo, bool pinned = false}) => ConversationSummary(
        id: id, title: id, pinned: pinned, updatedAt: daysAgo == null ? null : DateTime(2026, 10, 12).subtract(Duration(days: daysAgo)));
    final list = [c('old', daysAgo: 9), c('none'), c('new', daysAgo: 0), c('pin', daysAgo: 30, pinned: true), c('mid', daysAgo: 3)];
    expect(projectConversations(list).map((e) => e.id), ['pin', 'new', 'mid', 'old', 'none']);
    ProjectFile f(String p) => ProjectFile.fromJson({'path': p, 'name': p.split('/').last, 'size': 2048, 'mime': 'text/plain', 'modified': 1});
    expect(projectFileLine(f('notes/sub/大纲.md')), 'notes/sub · 2 KB');
    expect(projectFileLine(f('大纲.md')), '2 KB');
  });

  testWidgets('项目内：首屏只列本项目全部对话（置顶在前），没有文件 / 电脑 / 规则 / 起步建议；header 行 ‹ 和 ⋯', (tester) async {
    await _pump(tester, at: '/projects/p1');
    expect(find.byTooltip('项目对话'), findsOneWidget);
    expect(find.byTooltip('项目菜单'), findsOneWidget);
    expect(find.byTooltip('返回项目列表'), findsOneWidget);
    expect(find.text('今天想做点什么？'), findsNothing);
    final ys = [for (final t in ['择校', '单词计划', '真题第一轮', '政治大纲']) tester.getTopLeft(find.text(t)).dy];
    expect(ys, orderedEquals([...ys]..sort()));
    for (final gone in ['文件', '电脑', '回答用中文', '或者新开一段', '总结一下这个项目现在的进度']) {
      expect(find.text(gone), findsNothing, reason: gone);
    }
    expect(find.byType(TextField), findsOneWidget, reason: '底下的输入框 = 本项目新对话');
  });

  testWidgets('v2.91 §N 项目首屏最近对话：有状态画胶囊代替时间；打开对话后标题栏下浮出总结标题药丸', (tester) async {
    await _pump(tester, at: '/projects/p1');
    expect(find.text('进行中'), findsOneWidget); // 单词计划
    expect(find.text('等你回复'), findsOneWidget); // 择校
    expect(find.text('已完成'), findsNothing); // 真题第一轮没有 status：照旧写时间
    await tester.tap(find.text('单词计划'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 400));
    expect(find.byType(TitlePill), findsOneWidget);
    expect(find.descendant(of: find.byType(TitlePill), matching: find.text('单词计划')), findsOneWidget);
    expect(tester.state<TitlePillState>(find.byType(TitlePill)).shown.value, isTrue);
    await tester.pump(Timing.pillHold);
    expect(tester.state<TitlePillState>(find.byType(TitlePill)).shown.value, isFalse);
    await _settle(tester);
  });

  testWidgets('项目首屏：点最近对话 → 打开续聊；⋯ 菜单 = 列表同一份', (tester) async {
    await _pump(tester, at: '/projects/p1');
    await tester.tap(find.text('单词计划'));
    await _settle(tester);
    expect(find.text('续聊 c2'), findsOneWidget);
    expect(find.byType(ProjectHome), findsNothing);
    await tester.tap(find.byTooltip('项目菜单'));
    await _settle(tester);
    for (final t in ['项目文件', '电脑', '规则与档案', '编辑名称和图标', '删除项目']) {
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
}
