// 项目列表（v0.73）：页头“N 个项目 · 最近 …” + 衬线大标题；按最近活动排序；
// 卡片 ⋯ 菜单：编辑名称和图标（只 PATCH 改过的字段，没改不发请求）、删除（先确认，确认后 DELETE 并从列表消失）；
// 加载中是和卡片同高的骨架；新建表单的图标选择会带进 POST。
import 'package:assistant/app.dart';
import 'package:assistant/core/api.dart';
import 'package:assistant/core/cache.dart';
import 'package:assistant/core/chat_socket.dart';
import 'package:assistant/core/session.dart';
import 'package:assistant/features/projects/project_form.dart';
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
  final calls = <String>[];
  final bodies = <Object?>[];

  @override
  Future<dynamic> get(String path) async {
    if (path == '/api/inbox') return {'unread': 0, 'latest': null};
    if (path == '/api/projects') return [...projects];
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

Future<_Api> _pump(WidgetTester tester) async {
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
}
