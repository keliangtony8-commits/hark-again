// 项目档案：模型解析（老服务器没有字段 → 空；briefLine 跳过标题和列表符号）；
// 档案页进页静默 reload（拿到助手刚改的版本）、显示“助手更新于”；编辑 → 保存走 PATCH {brief}，回到查看；
// 空档案显示空态 + “自己写”；改了没保存点取消要确认；规则行点开表单改 rules。
import 'package:assistant/core/api.dart';
import 'package:assistant/core/cache.dart';
import 'package:assistant/core/resource.dart';
import 'package:assistant/features/projects/project_brief_screen.dart';
import 'package:assistant/models/resources.dart';
import 'package:assistant/theme/app_theme.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';

class FakeApi implements Api {
  FakeApi(this.project);
  Map<String, dynamic> project;
  final calls = <String>[];
  final bodies = <Object?>[];

  @override
  Future<dynamic> get(String path) async {
    calls.add('GET $path');
    return [project];
  }

  @override
  Future<dynamic> patch(String path, [Object? body]) async {
    calls.add('PATCH $path');
    bodies.add(body);
    final b = (body as Map).cast<String, dynamic>();
    project = {
      ...project,
      ...b,
      if (b.containsKey('brief')) ...{'brief': (b['brief'] as String).trim(), 'brief_by': 'user', 'brief_updated_at': DateTime.now().toIso8601String()},
    };
    return project;
  }

  @override
  dynamic noSuchMethod(Invocation i) => throw UnimplementedError();
}

Map<String, dynamic> proj({String brief = '', String? by}) => {
      'id': 'p1',
      'name': '考研',
      'emoji': '📚',
      'rules': '',
      'brief': brief,
      'brief_by': by,
      'brief_updated_at': by == null ? null : DateTime.now().subtract(const Duration(minutes: 3)).toIso8601String(),
    };

Future<ProviderContainer> pump(WidgetTester tester, FakeApi api) async {
  tester.view.physicalSize = const Size(800, 1600);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  final c = ProviderContainer(overrides: [apiProvider.overrideWithValue(api), cacheStoreProvider.overrideWithValue(MemoryCacheStore())]);
  addTearDown(c.dispose);
  await c.read(projectsProvider.future);
  await tester.pumpWidget(UncontrolledProviderScope(
    container: c,
    child: MaterialApp.router(
      theme: buildTheme(Brightness.light),
      routerConfig: GoRouter(initialLocation: '/b', routes: [
        GoRoute(path: '/', builder: (_, _) => const Text('项目'), routes: [GoRoute(path: 'b', builder: (_, _) => const ProjectBriefScreen(id: 'p1'))]),
      ]),
    ),
  ));
  await tester.pumpAndSettle();
  return c;
}

void main() {
  test('模型：老服务器没有档案字段；briefLine 取第一行正文', () {
    final old = Project.fromJson({'id': 'x', 'name': 'n'});
    expect(old.brief, '');
    expect(old.briefBy, isNull);
    expect(old.briefLine, '');
    final p = Project.fromJson(proj(brief: '## 目标\n\n- 12 月考研\n- 每晚复盘', by: 'assistant'));
    expect(p.briefLine, '12 月考研');
    expect(p.briefUpdatedAt, isNotNull);
  });

  testWidgets('进页静默 reload，显示助手刚写的档案和戳', (tester) async {
    final api = FakeApi(proj());
    await pump(tester, api);
    expect(find.text('档案还是空的'), findsOneWidget);

    // 助手在对话里改了档案：再进一次页拿到新版本
    api.project = proj(brief: '## 目标\n12 月考研', by: 'assistant');
    await tester.pumpWidget(const SizedBox());
    await pump(tester, api);
    expect(api.calls.where((c) => c == 'GET /api/projects').length, greaterThanOrEqualTo(2));
    expect(find.text('12 月考研'), findsOneWidget);
    expect(find.textContaining('助手更新于'), findsOneWidget);
  });

  testWidgets('编辑 → 保存走 PATCH，回到查看并显示“你编辑于”', (tester) async {
    final api = FakeApi(proj(brief: '## 目标\n12 月考研', by: 'assistant'));
    await pump(tester, api);

    await tester.tap(find.text('编辑档案'));
    await tester.pumpAndSettle();
    final field = find.byType(TextField);
    expect(tester.widget<TextField>(field).controller!.text, '## 目标\n12 月考研');
    await tester.enterText(field, '## 目标\n找暑期实习');
    await tester.pump();
    await tester.tap(find.text('保存'));
    await tester.pumpAndSettle();

    expect(api.calls.last, 'PATCH /api/projects/p1');
    expect(api.bodies.last, {'brief': '## 目标\n找暑期实习'});
    expect(find.byType(TextField), findsNothing);
    expect(find.text('找暑期实习'), findsOneWidget);
    expect(find.textContaining('你编辑于'), findsOneWidget);
  });

  testWidgets('空档案点“自己写”进编辑；有改动点取消要确认', (tester) async {
    final api = FakeApi(proj());
    await pump(tester, api);
    await tester.tap(find.text('自己写'));
    await tester.pumpAndSettle();
    await tester.enterText(find.byType(TextField), '随便写点');
    await tester.pump();
    await tester.tap(find.text('取消'));
    await tester.pumpAndSettle();
    expect(find.text('放弃这次改动？'), findsOneWidget);
    await tester.tap(find.text('放弃'));
    await tester.pumpAndSettle();
    expect(find.byType(TextField), findsNothing);
    expect(api.calls.where((c) => c.startsWith('PATCH')), isEmpty);
  });

  testWidgets('规则行：表单改 rules', (tester) async {
    final api = FakeApi(proj());
    await pump(tester, api);
    await tester.tap(find.text('项目规则'));
    await tester.pumpAndSettle();
    await tester.enterText(find.byType(TextField), '回答都用英文');
    await tester.pump();
    await tester.tap(find.text('保存'));
    await tester.pumpAndSettle();
    expect(api.bodies.last, {'rules': '回答都用英文'});
    expect(find.text('回答都用英文'), findsOneWidget);
  });
}
