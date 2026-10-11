// 技能启用/停用：旧服务器没有 enabled = 启用；列表行尾开关 → POST disable/enable，停用的行变淡；
// 失败时开关拨回并提示服务器的话；编辑页的“启用”开关同样走 act，且不动输入框里没保存的改动。
import 'dart:async';

import 'package:assistant/core/api.dart';
import 'package:assistant/core/resource.dart';
import 'package:assistant/features/me/skills_screen.dart';
import 'package:assistant/models/resources.dart';
import 'package:assistant/theme/app_theme.dart';
import 'package:assistant/ui/motion.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';

Map<String, dynamic> skill(String id, String name, {bool builtin = true, bool? enabled}) =>
    {'id': id, 'name': name, 'description': '$name 的时候', 'body': '原文', 'builtin': builtin, 'enabled': ?enabled};

class FakeApi implements Api {
  FakeApi(this.skills);
  List<Map<String, dynamic>> skills;
  final calls = <String>[];
  String? fail;
  Completer<void>? gate; // 卡住服务器回包，看乐观状态

  @override
  Future<dynamic> get(String path) async => skills;

  @override
  Future<dynamic> post(String path, [Object? body]) async {
    calls.add('POST $path');
    if (gate != null) await gate!.future;
    if (fail != null) throw ApiError(fail!, 400);
    final parts = path.split('/');
    final id = parts[parts.length - 2];
    final i = skills.indexWhere((s) => s['id'] == id);
    skills[i] = {...skills[i], 'enabled': parts.last == 'enable'};
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

bool dimmedOf(WidgetTester tester, String name) =>
    tester.widget<Dimmed>(find.ancestor(of: find.text(name), matching: find.byType(Dimmed))).dimmed;

Finder switchIn(String name) =>
    find.descendant(of: find.ancestor(of: find.text(name), matching: find.byType(Dimmed)), matching: find.byType(Switch));

void main() {
  test('旧服务器没有 enabled 字段 = 启用', () {
    expect(Skill.fromJson(skill('a', 'A')).enabled, isTrue);
    expect(Skill.fromJson(skill('a', 'A', enabled: false)).enabled, isFalse);
  });

  testWidgets('列表开关：停用变淡，再启用恢复', (tester) async {
    final api = FakeApi([skill('writing', '写作'), skill('mine', '周报', builtin: false, enabled: false)]);
    final c = await pump(tester, api, const SkillsScreen());

    expect(dimmedOf(tester, '写作'), isFalse);
    expect(dimmedOf(tester, '周报'), isTrue);
    expect(tester.widget<Switch>(switchIn('周报')).value, isFalse);

    await tester.tap(switchIn('写作'));
    await tester.pumpAndSettle();
    expect(api.calls, ['POST /api/catalog/skills/writing/disable']);
    expect(dimmedOf(tester, '写作'), isTrue);
    expect(c.read(skillsProvider).value!.firstWhere((s) => s.id == 'writing').enabled, isFalse);

    await tester.tap(switchIn('周报'));
    await tester.pumpAndSettle();
    expect(api.calls.last, 'POST /api/catalog/skills/mine/enable');
    expect(dimmedOf(tester, '周报'), isFalse);
  });

  testWidgets('失败：开关拨回、提示服务器的话', (tester) async {
    final api = FakeApi([skill('writing', '写作')])
      ..fail = '没有这个技能'
      ..gate = Completer();
    await pump(tester, api, const SkillsScreen());
    await tester.tap(switchIn('写作'));
    await tester.pump();
    expect(tester.widget<Switch>(switchIn('写作')).value, isFalse, reason: '乐观先拨');
    expect(tester.widget<Switch>(switchIn('写作')).onChanged, isNull, reason: '回包前不能再拨');
    api.gate!.complete();
    await tester.pumpAndSettle();
    expect(find.text('没有这个技能'), findsOneWidget);
    expect(tester.widget<Switch>(switchIn('写作')).value, isTrue);
    expect(dimmedOf(tester, '写作'), isFalse);
  });

  testWidgets('编辑页开关：走 act，不动未保存的输入', (tester) async {
    final api = FakeApi([skill('mine', '周报', builtin: false)]);
    final c = await pump(tester, api, const SkillEditorScreen(id: 'mine'));
    await tester.enterText(find.widgetWithText(TextField, '名称'), '周报（改）');
    await tester.tap(find.byType(Switch));
    await tester.pumpAndSettle();
    expect(api.calls, ['POST /api/catalog/skills/mine/disable']);
    expect(find.text('已停用：我看不到它，也不会用它'), findsOneWidget);
    expect(find.text('周报（改）'), findsOneWidget);
    expect(c.read(skillsProvider).value!.single.enabled, isFalse);
  });

  testWidgets('新建页没有启用开关', (tester) async {
    await pump(tester, FakeApi([]), const SkillEditorScreen(id: 'new'));
    expect(find.byType(Switch), findsNothing);
  });
}
