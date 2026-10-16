// 记忆笔记（v2.21）：纯逻辑（第一行、副标题、多词筛选、路径预览、读屏、页头计数）+ 页面：
// 记忆页出现“主题笔记”一节且被同一个搜索框筛、只有笔记没有记忆时不显示起步卡；点开阅读（Markdown）→ 编辑 → 保存走 PATCH 只带改了的字段；
// “+”选主题笔记 → 新建页实时预览路径 → POST；阅读页删除要确认；带着改动取消要确认。
import 'package:assistant/core/cache.dart';
import 'package:assistant/core/api.dart';
import 'package:assistant/features/me/memory_notes.dart';
import 'package:assistant/features/me/memory_screen.dart';
import 'package:assistant/models/memory.dart';
import 'package:assistant/models/memory_note.dart';
import 'package:assistant/models/resources.dart';
import 'package:assistant/theme/app_theme.dart';
import 'package:assistant/ui/glass.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';

Map<String, dynamic> note(String id, String path, String title, String kind, String body) =>
    {'id': id, 'path': path, 'title': title, 'kind': kind, 'body': body, 'updated_at': DateTime.now().toUtc().toIso8601String()};

class FakeApi implements Api {
  FakeApi(this.notes, {this.memories = const []});
  List<Map<String, dynamic>> notes;
  List<Map<String, dynamic>> memories;
  final calls = <String>[];

  @override
  Future<dynamic> get(String path) async {
    if (path == '/api/memories') return memories;
    if (path == '/api/memory-notes') return notes;
    if (path == '/api/memory-digest') return {'text': null, 'generated_at': null, 'count': 0, 'memories': memories.length, 'stale': false};
    throw UnimplementedError(path);
  }

  @override
  Future<dynamic> post(String path, [Object? body]) async {
    calls.add('POST $path $body');
    final b = (body as Map).cast<String, dynamic>();
    final kind = b['kind'] as String? ?? 'misc';
    final j = note('n${notes.length + 1}', notePathPreview(b['path'] as String, kind), b['title'] as String? ?? (b['path'] as String), kind, b['body'] as String? ?? '');
    notes = [j, ...notes];
    return j;
  }

  @override
  Future<dynamic> patch(String path, [Object? body]) async {
    calls.add('PATCH $path $body');
    final id = path.split('/').last;
    final i = notes.indexWhere((n) => n['id'] == id);
    notes[i] = {...notes[i], ...(body as Map).cast<String, dynamic>()};
    return notes[i];
  }

  @override
  Future<dynamic> delete(String path) async {
    calls.add('DELETE $path');
    notes = [for (final n in notes) if (n['id'] != path.split('/').last) n];
  }

  @override
  dynamic noSuchMethod(Invocation i) => throw UnimplementedError();
}

Future<void> pump(WidgetTester tester, FakeApi api) async {
  tester.view.physicalSize = const Size(800, 1600);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  final router = GoRouter(initialLocation: '/me/memory', routes: [
    GoRoute(path: '/me/memory', builder: (_, _) => const MemoryScreen(), routes: [
      GoRoute(path: 'notes/:id', builder: (_, s) => MemoryNoteScreen(id: s.pathParameters['id']!)),
    ]),
  ]);
  await tester.pumpWidget(ProviderScope(
    overrides: [apiProvider.overrideWithValue(api), cacheStoreProvider.overrideWithValue(MemoryCacheStore())],
    child: MaterialApp.router(theme: buildTheme(Brightness.light), routerConfig: router),
  ));
  await tester.pumpAndSettle();
}

final mom = note('m', 'people/妈妈', '妈妈', 'contact', '# 妈妈\n- 生日 6 月 1 日\n- 在老家开花店');
final plan = note('k', '考研计划', '考研', 'project', '目标：浙大计算机');

void main() {
  test('logic', () {
    final list = [MemoryNote.fromJson(mom), MemoryNote.fromJson(plan)];
    expect(noteFirstLine('\n## 妈妈\n- x'), '妈妈');
    expect(noteFirstLine('  \n'), '');
    expect(noteSubtitle(list[0]), '人 · people/妈妈'); // 第一行就是标题 → 换成路径
    expect(noteSubtitle(list[1]), '项目 · 目标：浙大计算机');
    expect(noteSubtitle(MemoryNote.fromJson(note('e', 'x', 'x', 'misc', ''))), '其他 · 还没写内容');
    expect(filterNotes(list, '花店').map((n) => n.id), ['m']);
    expect(filterNotes(list, '浙大 目标').map((n) => n.id), ['k']);
    expect(filterNotes(list, '项目').map((n) => n.id), ['k']); // 类别名也能搜
    expect(filterNotes(list, '').length, 2);
    expect(notePathPreview('妈妈', 'contact'), 'people/妈妈');
    expect(notePathPreview('/学校.md', 'place'), 'locations/学校');
    expect(notePathPreview('work/abc', 'contact'), 'work/abc');
    expect(notePathPreview('考研', 'project'), '考研');
    expect(list[0].name, '妈妈');
    expect(list[0].folder, 'people');
    expect(list[1].folder, isNull);
    expect(noteSemantics(list[1]), '笔记 考研，项目，目标：浙大计算机');
    expect(noteKindLabel('weird'), '其他');
    expect(memorySummary(const [], notes: 2), '2 篇笔记');
    expect(memorySummary([MemoryItem.fromJson({'id': 'a', 'content': 'x', 'category': 'food'})], notes: 1), '记得 1 件事 · 1 篇笔记');
  });

  testWidgets('section, search, read, edit → PATCH only changed', (tester) async {
    final api = FakeApi([mom, plan]);
    await pump(tester, api);
    expect(find.text('还没有记忆'), findsNothing); // 只有笔记也不是空页
    expect(find.text('主题笔记'), findsOneWidget);
    expect(find.text('妈妈'), findsOneWidget);
    expect(find.text('考研'), findsOneWidget);
    expect(find.text('2 篇笔记'), findsOneWidget);

    await tester.tap(find.text('妈妈'));
    await tester.pumpAndSettle();
    expect(find.text('笔记'), findsOneWidget);
    expect(find.textContaining('在老家开花店'), findsOneWidget);
    expect(find.text('people/妈妈'), findsOneWidget);

    await tester.tap(find.text('编辑'));
    await tester.pumpAndSettle();
    expect(find.text('编辑笔记'), findsOneWidget);
    final save = find.widgetWithText(FilledButton, '保存');
    expect(tester.widget<FilledButton>(save).onPressed, isNull); // 没改不能存
    await tester.enterText(find.byType(TextField).last, '# 妈妈\n- 生日 6 月 1 日\n- 花店开在镇上');
    await tester.pumpAndSettle();
    await tester.tap(save);
    await tester.pumpAndSettle();
    expect(api.calls.single, 'PATCH /api/memory-notes/m {body: # 妈妈\n- 生日 6 月 1 日\n- 花店开在镇上}');
    expect(find.text('笔记'), findsOneWidget); // 回到阅读态
    expect(find.textContaining('花店开在镇上'), findsOneWidget);

    // 删除要确认
    await tester.tap(find.byTooltip('删除笔记'));
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(PillButton, '删除'));
    await tester.pumpAndSettle();
    expect(api.calls.last, 'DELETE /api/memory-notes/m');
    expect(find.text('主题笔记'), findsOneWidget);
    expect(find.text('妈妈'), findsNothing);
  });

  testWidgets('search filters notes; + → new note with path preview', (tester) async {
    final api = FakeApi([mom, plan], memories: [for (var i = 0; i < 6; i++) {'id': 'x$i', 'content': '杂事$i', 'category': 'general'}]);
    await pump(tester, api);
    await tester.enterText(find.byType(TextField).first, '浙大');
    await tester.pumpAndSettle();
    expect(find.text('考研'), findsOneWidget);
    expect(find.text('妈妈'), findsNothing);
    expect(find.text('没有匹配的记忆'), findsNothing); // 笔记命中了就不算没结果
    await tester.enterText(find.byType(TextField).first, '火星');
    await tester.pumpAndSettle();
    expect(find.text('没有匹配的记忆'), findsOneWidget);
    await tester.enterText(find.byType(TextField).first, '');
    await tester.pumpAndSettle();

    await tester.tap(find.byTooltip('新增'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('主题笔记').last);
    await tester.pumpAndSettle();
    expect(find.text('新笔记'), findsOneWidget);
    await tester.enterText(find.widgetWithText(TextField, '名字'), '王老师');
    await tester.pumpAndSettle();
    expect(find.text('会存成 people/王老师'), findsOneWidget);
    await tester.tap(find.widgetWithText(ChoiceChip, '地方'));
    await tester.pumpAndSettle();
    expect(find.text('会存成 locations/王老师'), findsOneWidget);
    await tester.tap(find.widgetWithText(ChoiceChip, '人'));
    await tester.enterText(find.byType(TextField).last, '导师，研究 NLP');
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(FilledButton, '保存'));
    await tester.pumpAndSettle();
    expect(api.calls.single, 'POST /api/memory-notes {path: 王老师, kind: contact, body: 导师，研究 NLP}');
    expect(find.text('王老师'), findsOneWidget); // 回到记忆页，新笔记在列表里
  });

  testWidgets('cancel with changes asks first', (tester) async {
    final api = FakeApi([plan]);
    await pump(tester, api);
    await tester.tap(find.text('考研'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('编辑'));
    await tester.pumpAndSettle();
    await tester.enterText(find.byType(TextField).last, '目标：清华');
    await tester.pumpAndSettle();
    await tester.tap(find.text('取消'));
    await tester.pumpAndSettle();
    expect(find.text('放弃没保存的改动？'), findsOneWidget);
    await tester.tap(find.widgetWithText(PillButton, '放弃'));
    await tester.pumpAndSettle();
    expect(find.text('笔记'), findsOneWidget);
    expect(find.textContaining('浙大计算机'), findsOneWidget);
    expect(api.calls, isEmpty);
  });
}
