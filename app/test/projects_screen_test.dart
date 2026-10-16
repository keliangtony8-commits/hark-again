// 项目页（v3.2.2 按 Hark 真机截图）：列表 = 占满整行的大字项目名 + 下一行状态胶囊，按最近活动排序（没有页头摘要 / emoji / ⋯，菜单 = 长按），
// 不是当前的项目变灰（projectIsCurrent）、没有输入框；⋯ 菜单：编辑（只 PATCH 改过的字段）、删除（先确认）、电脑；
// v2.95 项目 = 一段对话：进项目直接是那段聊天（仍在一级外壳下，顶栏在），左上 + → ≡ 同一颗钮，≡ 打开项目切换抽屉、开着时变 +；
// 顶栏下项目名药丸 = 项目菜单。
import 'package:assistant/app.dart';
import 'package:assistant/core/api.dart';
import 'package:assistant/core/cache.dart';
import 'package:assistant/core/chat_socket.dart';
import 'package:assistant/core/session.dart';
import 'package:assistant/features/chat/status_capsule.dart';
import 'package:assistant/features/projects/project_files_sheet.dart' show projectFileLine;
import 'package:assistant/features/projects/project_form.dart';
import 'package:assistant/features/projects/project_switcher.dart';
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
    {'id': 'p1', 'name': '考研', 'emoji': '📚', 'rules': '回答用中文', 'conversation_id': 'c1', 'status': 'done', 'last_active_at': now.subtract(const Duration(days: 3)).toIso8601String()},
    {'id': 'p2', 'name': '找实习', 'emoji': '💼', 'rules': '', 'last_active_at': now.subtract(const Duration(minutes: 5)).toIso8601String()},
  ];
  final calls = <String>[];
  final bodies = <Object?>[];

  @override
  Future<dynamic> get(String path) async {
    if (path == '/api/inbox') return {'unread': 0, 'latest': null};
    if (path == '/api/projects') return [...projects];
    // v2.95：项目范围 = 那一段对话（≤1 项，服务器没有就建）
    if (path == '/api/conversations?project_id=p1') return [{'id': 'c1', 'title': '考研', 'status': 'done'}];
    if (path == '/api/conversations?project_id=p2') return [{'id': 'c9', 'title': '找实习'}];
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

/// v3.2.2 列表行不再画 ⋯：菜单 = 长按那一行。
Future<void> _openMenu(WidgetTester tester, String name) => tester.longPress(find.text(name));

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

  testWidgets('列表（v3.2.2 按 Hark）：没有页头摘要 / emoji / ⋯，大字名占满整行、胶囊在名字下一行，按最近活动排序、汇总状态胶囊、不是当前的变灰、没有输入框', (tester) async {
    await _pump(tester);
    expect(find.textContaining('个项目'), findsNothing, reason: 'Hark 列表没有页头小标签');
    expect(find.text('📚'), findsNothing, reason: '列表不画 emoji');
    expect(find.byTooltip('更多'), findsNothing, reason: '菜单 = 长按');
    final name = tester.getRect(find.text('考研'));
    final cap = tester.getRect(find.byType(StatusCapsule));
    expect(cap.top, greaterThan(name.bottom - 1), reason: '状态胶囊在名字下一行');
    expect(cap.left, closeTo(name.left, 1), reason: '与名字左对齐');
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

  testWidgets('v2.95 进项目：直接是那段聊天（没有对话列表首屏），顶栏仍在，左上 + 转成 ≡；顶栏下项目名药丸', (tester) async {
    await _pump(tester);
    await tester.tap(find.text('考研'));
    await _settle(tester);
    expect(find.text('续聊 c1'), findsOneWidget, reason: '项目的那一段对话自动打开');
    expect(find.byType(ProjectPill), findsOneWidget);
    expect(find.descendant(of: find.byType(ProjectPill), matching: find.text('📚 考研')), findsOneWidget);
    expect(find.text('主页'), findsOneWidget, reason: '一级外壳顶栏不淡出');
    expect(find.byTooltip('我的'), findsOneWidget);
    expect(tester.widget<MenuPlusIcon>(find.byType(MenuPlusIcon).last).plus, isFalse);
    expect(find.byTooltip('项目'), findsOneWidget);
    for (final gone in ['返回项目列表', '项目菜单', '项目对话', '新对话']) {
      expect(find.byTooltip(gone), findsNothing, reason: gone);
    }
    expect(find.byType(TextField), findsOneWidget);
  });

  testWidgets('v2.95 ≡ 打开项目切换抽屉（当前项目高亮、带状态胶囊），开着时钮变 +；点别的项目 → 换到它的聊天', (tester) async {
    await _pump(tester, at: '/projects/p1');
    await tester.tap(find.byTooltip('项目'));
    await _settle(tester);
    expect(find.byType(ProjectSwitcher), findsOneWidget);
    expect(tester.widget<MenuPlusIcon>(find.byType(MenuPlusIcon).last).plus, isTrue);
    expect(find.byTooltip('新项目'), findsOneWidget);
    final inDrawer = find.descendant(of: find.byType(ProjectSwitcher), matching: find.text('找实习'));
    expect(inDrawer, findsOneWidget);
    expect(find.descendant(of: find.byType(ProjectSwitcher), matching: find.text('已完成')), findsOneWidget);
    final current = find.ancestor(of: find.descendant(of: find.byType(ProjectSwitcher), matching: find.text('考研')), matching: find.byType(Semantics));
    expect(tester.widgetList<Semantics>(current).any((w) => w.properties.selected == true), isTrue, reason: '当前项目高亮');
    await tester.tap(inDrawer);
    await _settle(tester);
    expect(find.byType(ProjectSwitcher), findsNothing);
    expect(find.text('续聊 c9'), findsOneWidget);
    expect(find.descendant(of: find.byType(ProjectPill), matching: find.text('💼 找实习')), findsOneWidget);
    expect(tester.widget<MenuPlusIcon>(find.byType(MenuPlusIcon).last).plus, isFalse);
  });

  testWidgets('v2.95 抽屉开着时点 + = 新建项目（收起抽屉、弹表单）', (tester) async {
    final api = await _pump(tester, at: '/projects/p1');
    await tester.tap(find.byTooltip('项目'));
    await _settle(tester);
    await tester.tap(find.byTooltip('新项目'));
    await _settle(tester);
    expect(find.byType(ProjectSwitcher), findsNothing);
    expect(find.text('新项目'), findsOneWidget, reason: '新建项目表单标题');
    await tester.enterText(find.widgetWithText(TextField, '名称'), '旅行');
    await tester.pump();
    await tester.tap(find.text('创建'));
    await _settle(tester);
    expect(find.text('新项目'), findsNothing);
    expect(api.calls, contains('POST /api/projects'));
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
    expect(tester.getCenter(find.byTooltip('项目')), before);
  });

  testWidgets('⋯ 菜单编辑：只发改过的字段；什么都没改不发请求', (tester) async {
    final api = await _pump(tester);
    await _openMenu(tester, '考研');
    await _settle(tester);
    await tester.tap(find.text('编辑名称和图标'));
    await _settle(tester);
    expect(find.text('编辑项目'), findsOneWidget);
    await tester.tap(find.text('保存'));
    await _settle(tester);
    expect(api.calls.where((c) => c.startsWith('PATCH')), isEmpty);

    await _openMenu(tester, '考研');
    await _settle(tester);
    await tester.tap(find.text('编辑名称和图标'));
    await _settle(tester);
    await tester.tap(find.text('🎯'));
    await tester.pump();
    await tester.tap(find.text('保存'));
    await _settle(tester);
    expect(api.calls.last, 'PATCH /api/projects/p1');
    expect(api.bodies.last, {'emoji': '🎯'});
    expect(find.text('🎯'), findsNothing, reason: 'v3.2.2 列表不画 emoji（emoji 在项目内药丸上）');
  });

  testWidgets('⋯ 菜单删除：取消不删，确认后 DELETE 并从列表消失', (tester) async {
    final api = await _pump(tester);
    await _openMenu(tester, '找实习');
    await _settle(tester);
    await tester.tap(find.text('删除项目'));
    await _settle(tester);
    expect(find.text('删除“找实习”？'), findsOneWidget);
    await tester.tap(find.text('取消'));
    await _settle(tester);
    expect(api.calls, isEmpty);

    await _openMenu(tester, '找实习');
    await _settle(tester);
    await tester.tap(find.text('删除项目'));
    await _settle(tester);
    await tester.tap(find.text('删除'));
    await _settle(tester);
    expect(api.calls, ['DELETE /api/projects/p2']);
    expect(find.text('找实习'), findsNothing);
    expect(find.text('考研'), findsOneWidget, reason: '剩下的那个还在');
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

  test('projectFileLine 带文件夹', () {
    ProjectFile f(String p) => ProjectFile.fromJson({'path': p, 'name': p.split('/').last, 'size': 2048, 'mime': 'text/plain', 'modified': 1});
    expect(projectFileLine(f('notes/sub/大纲.md')), 'notes/sub · 2 KB');
    expect(projectFileLine(f('大纲.md')), '2 KB');
  });

  testWidgets('v2.95 项目名药丸 = 项目菜单（和列表 ⋯ 同一份）', (tester) async {
    await _pump(tester, at: '/projects/p1');
    await tester.tap(find.byType(ProjectPill));
    await _settle(tester);
    for (final t in ['项目文件', '电脑', '规则与档案', '编辑名称和图标', '删除项目']) {
      expect(find.text(t), findsOneWidget);
    }
  });

  testWidgets('项目内删除（药丸菜单）：确认后退回列表', (tester) async {
    final api = await _pump(tester, at: '/projects/p1');
    await tester.tap(find.byType(ProjectPill));
    await _settle(tester);
    await tester.tap(find.text('删除项目'));
    await _settle(tester);
    await tester.tap(find.text('删除'));
    await _settle(tester);
    expect(api.calls, ['DELETE /api/projects/p1']);
    expect(find.byType(ProjectPill), findsNothing);
    expect(find.text('找实习'), findsOneWidget, reason: '退回列表，剩下的那个还在');
  });
}
