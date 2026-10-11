// 技能页：老服务器没有 customized = false；自定义版在“内置”分组带“已自定义”、不能左滑删；
// 内置只读页“复制一份来改”→ POST customize、输入框可编辑、保存走 PUT；自定义版“恢复默认”确认后 POST reset、
// 输入框回到原文并只读；取消确认不发请求；失败提示服务器的话。
import 'package:assistant/core/api.dart';
import 'package:assistant/core/resource.dart';
import 'package:assistant/features/me/skills_screen.dart';
import 'package:assistant/models/resources.dart';
import 'package:assistant/theme/app_theme.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';

Map<String, dynamic> skill(String id, String name, {bool builtin = true, bool? customized, String body = '原文'}) => {
      'id': id, 'name': name, 'description': '$name 的时候', 'body': body, 'builtin': builtin, 'customized': ?customized,
    };

class FakeApi implements Api {
  FakeApi(this.skills);
  List<Map<String, dynamic>> skills;
  final calls = <String>[];
  String? fail;

  @override
  Future<dynamic> get(String path) async {
    calls.add('GET $path');
    return skills;
  }

  @override
  Future<dynamic> post(String path, [Object? body]) async {
    calls.add('POST $path');
    if (fail != null) throw ApiError(fail!, 400);
    final parts = path.split('/');
    final id = parts[parts.length - 2], action = parts.last;
    final i = skills.indexWhere((s) => s['id'] == id);
    skills[i] = action == 'customize'
        ? {...skills[i], 'builtin': false, 'customized': true}
        : skill(id, '写作');
    return skills[i];
  }

  @override
  Future<dynamic> put(String path, Object body) async {
    calls.add('PUT $path');
    final id = path.split('/').last;
    final i = skills.indexWhere((s) => s['id'] == id);
    skills[i] = {...skills[i], ...(body as Map).cast<String, dynamic>()};
    return skills[i];
  }

  @override
  dynamic noSuchMethod(Invocation i) => throw UnimplementedError();
}

Future<ProviderContainer> pump(WidgetTester tester, FakeApi api, Widget home) async {
  tester.view.physicalSize = const Size(800, 1600);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  final c = ProviderContainer(overrides: [apiProvider.overrideWithValue(api)]);
  addTearDown(c.dispose);
  await c.read(skillsProvider.future);
  await tester.pumpWidget(UncontrolledProviderScope(
    container: c,
    // 编辑页保存后 context.pop()：放在一个子路由里，有地方可退
    child: MaterialApp.router(
      theme: buildTheme(Brightness.light),
      routerConfig: GoRouter(initialLocation: '/e', routes: [
        GoRoute(path: '/', builder: (_, _) => const Text('列表'), routes: [GoRoute(path: 'e', builder: (_, _) => home)]),
      ]),
    ),
  ));
  await tester.pumpAndSettle();
  return c;
}

TextField field(WidgetTester tester, String label) =>
    tester.widget<TextField>(find.widgetWithText(TextField, label));

void main() {
  test('customized defaults to false; fromBuiltin covers both', () {
    expect(Skill.fromJson(skill('a', 'x')).customized, false);
    expect(Skill.fromJson(skill('a', 'x', builtin: false, customized: true)).fromBuiltin, true);
    expect(Skill.fromJson(skill('a', 'x', builtin: false)).fromBuiltin, false);
  });

  testWidgets('list groups customized under builtin with a pill', (tester) async {
    final api = FakeApi([
      skill('writing', '写作', builtin: false, customized: true),
      skill('github', 'GitHub'),
      skill('weekly', '周报', builtin: false),
    ]);
    await pump(tester, api, const SkillsScreen());
    expect(find.text('已自定义'), findsOneWidget);
    // 我的技能分组只有周报：它在“内置”标题之前
    final mineY = tester.getTopLeft(find.text('周报')).dy;
    final builtinY = tester.getTopLeft(find.text('内置')).dy;
    expect(mineY < builtinY, true);
    expect(tester.getTopLeft(find.text('写作')).dy > builtinY, true);
    expect(find.byType(Dismissible), findsOneWidget, reason: '只有自己写的能左滑删');
  });

  testWidgets('customize a builtin then save via PUT', (tester) async {
    final api = FakeApi([skill('writing', '写作')]);
    final c = await pump(tester, api, const SkillEditorScreen(id: 'writing'));
    expect(field(tester, '名称').readOnly, true);
    expect(find.text('保存'), findsNothing);
    expect(find.text('恢复默认'), findsNothing);

    await tester.tap(find.text('复制一份来改'));
    await tester.pumpAndSettle();
    expect(api.calls.last, 'POST /api/catalog/skills/writing/customize');
    expect(field(tester, '名称').readOnly, false);
    expect(find.text('复制一份来改'), findsNothing);
    expect(find.text('恢复默认'), findsOneWidget);
    expect(c.read(skillsProvider).value!.single.customized, true);

    await tester.enterText(find.widgetWithText(TextField, '名称'), '写作（我的）');
    await tester.tap(find.text('保存'));
    await tester.pumpAndSettle();
    expect(api.calls.last, 'PUT /api/catalog/skills/writing');
    expect(c.read(skillsProvider).value!.single.name, '写作（我的）');
    expect(find.text('列表'), findsOneWidget, reason: '保存后退回');
  });

  testWidgets('reset asks first, then restores builtin text read-only', (tester) async {
    final api = FakeApi([skill('writing', '写作（我的）', builtin: false, customized: true, body: '我的步骤')]);
    await pump(tester, api, const SkillEditorScreen(id: 'writing'));
    expect(field(tester, '名称').readOnly, false);

    await tester.tap(find.text('恢复默认'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('取消'));
    await tester.pumpAndSettle();
    expect(api.calls.where((x) => x.startsWith('POST')), isEmpty);

    await tester.tap(find.text('恢复默认'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('恢复默认').last);
    await tester.pumpAndSettle();
    expect(api.calls.last, 'POST /api/catalog/skills/writing/reset');
    expect(field(tester, '名称').controller!.text, '写作');
    expect(field(tester, '步骤（Markdown）').controller!.text, '原文');
    expect(field(tester, '名称').readOnly, true);
    expect(find.text('复制一份来改'), findsOneWidget);
  });

  testWidgets('customize failure shows the server message', (tester) async {
    final api = FakeApi([skill('writing', '写作')])..fail = '服务器忙';
    await pump(tester, api, const SkillEditorScreen(id: 'writing'));
    await tester.tap(find.text('复制一份来改'));
    await tester.pumpAndSettle();
    expect(find.text('服务器忙'), findsOneWidget);
    expect(field(tester, '名称').readOnly, true);
  });
}
