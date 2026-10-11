// 记忆页：纯逻辑（分类顺序/计数、多词搜索含分类名、分类筛选）+ 页面：
// 概括卡不自动生成、点生成才 POST、改记忆后静默重取变“记忆有更新”、生成失败提示且旧概括保留、
// 老服务器没有接口 → 不显示卡；搜索框和分类条过滤列表、无结果可清除；编辑能改分类。
import 'package:assistant/core/api.dart';
import 'package:assistant/features/me/memory_screen.dart';
import 'package:assistant/models/memory.dart';
import 'package:assistant/models/resources.dart';
import 'package:assistant/theme/app_theme.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

Map<String, dynamic> mem(String id, String content, String cat) =>
    {'id': id, 'content': content, 'category': cat, 'updated_at': DateTime.now().toUtc().toIso8601String()};

class FakeApi implements Api {
  FakeApi(this.memories, {this.digest, this.digestMissing = false});
  List<Map<String, dynamic>> memories;
  Map<String, dynamic>? digest;
  bool digestMissing, failGenerate = false;
  final calls = <String>[];
  int version = 0;

  Map<String, dynamic> get _digest =>
      digest ?? {'text': null, 'generated_at': null, 'count': 0, 'memories': memories.length, 'stale': false};

  @override
  Future<dynamic> get(String path) async {
    calls.add('GET $path');
    if (path == '/api/memories') return memories;
    if (path == '/api/memory-digest') {
      if (digestMissing) throw ApiError('not found', 404);
      return {..._digest, 'memories': memories.length};
    }
    throw UnimplementedError(path);
  }

  @override
  Future<dynamic> post(String path, [Object? body]) async {
    calls.add('POST $path');
    if (path == '/api/memory-digest') {
      if (failGenerate) throw ApiError('生成失败', 502);
      version++;
      digest = {'text': '你是大二学生，不吃辣（$version）', 'generated_at': DateTime.now().toUtc().toIso8601String(), 'count': memories.length, 'memories': memories.length, 'stale': false};
      return digest;
    }
    throw UnimplementedError(path);
  }

  @override
  Future<dynamic> patch(String path, [Object? body]) async {
    calls.add('PATCH $path $body');
    final id = path.split('/').last;
    final i = memories.indexWhere((m) => m['id'] == id);
    memories[i] = {...memories[i], ...(body as Map).cast<String, dynamic>()};
    if (digest != null) digest = {...digest!, 'stale': true};
    return memories[i];
  }

  @override
  dynamic noSuchMethod(Invocation i) => throw UnimplementedError();
}

Future<void> pump(WidgetTester tester, FakeApi api) async {
  tester.view.physicalSize = const Size(800, 1600);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(ProviderScope(
    overrides: [apiProvider.overrideWithValue(api)],
    child: MaterialApp(theme: buildTheme(Brightness.light), home: const MemoryScreen()),
  ));
  await tester.pumpAndSettle();
}

final sample = [mem('a', '不吃辣', 'food'), mem('b', '大二学生，学计算机', 'profile'), mem('c', '周末喜欢爬山', 'weird'), mem('d', '喜欢吃甜的', 'food')];

void main() {
  test('categories, counts, filter', () {
    final list = [for (final j in sample) MemoryItem.fromJson(j)];
    expect(categoryCounts(list), [('profile', 1), ('food', 2), ('weird', 1)]);
    expect(categoryLabel('weird'), 'weird');
    expect(filterMemories(list).map((g) => g.$1), ['profile', 'food', 'weird']);
    expect(filterMemories(list, query: '喜欢').expand((g) => g.$2).map((m) => m.id), ['d', 'c']);
    expect(filterMemories(list, query: '喜欢 甜').expand((g) => g.$2).map((m) => m.id), ['d']);
    expect(filterMemories(list, query: '饮食').expand((g) => g.$2).map((m) => m.id), ['a', 'd']); // 分类中文名也能搜
    expect(filterMemories(list, query: '喜欢', category: 'weird').single.$2.single.id, 'c');
    expect(filterMemories(list, query: '没有这个'), isEmpty);
    final d = MemoryDigest.fromJson({'text': 'x', 'generated_at': '2026-10-11T00:00:00Z', 'count': 2, 'memories': 3, 'stale': true});
    expect((d.hasText, d.count, d.memories, d.stale), (true, 2, 3, true));
    expect(const MemoryDigest().hasText, false);
  });

  testWidgets('digest: never automatic, generate on tap, stale after edit', (tester) async {
    final api = FakeApi([...sample]);
    await pump(tester, api);
    expect(find.text('我对你的了解'), findsOneWidget);
    expect(find.textContaining('把你的 4 条记忆'), findsOneWidget);
    expect(api.calls.where((c) => c.startsWith('POST')), isEmpty);

    await tester.tap(find.text('生成'));
    await tester.pumpAndSettle();
    expect(api.calls.where((c) => c == 'POST /api/memory-digest').length, 1);
    expect(find.text('你是大二学生，不吃辣（1）'), findsOneWidget);
    expect(find.textContaining('根据 4 条记忆'), findsOneWidget);
    expect(find.text('记忆有更新'), findsNothing);

    // 编辑：改内容 + 改分类 → PATCH 一次，列表跟着变，概括卡静默重取后提示过期
    await tester.tap(find.text('不吃辣'));
    await tester.pumpAndSettle();
    await tester.enterText(find.byType(TextField).last, '不吃辣也不吃香菜');
    await tester.tap(find.widgetWithText(ChoiceChip, '关于你').last);
    await tester.pumpAndSettle();
    await tester.tap(find.text('保存'));
    await tester.pumpAndSettle();
    final patch = api.calls.singleWhere((c) => c.startsWith('PATCH'));
    expect(patch, contains('不吃辣也不吃香菜'));
    expect(patch, contains('profile'));
    expect(find.text('记忆有更新'), findsOneWidget);
    expect(api.calls.where((c) => c == 'POST /api/memory-digest').length, 1); // 过期也不自动重写

    api.failGenerate = true;
    await tester.tap(find.text('更新'));
    await tester.pumpAndSettle();
    expect(find.text('生成失败，稍后再试'), findsOneWidget);
    expect(find.text('你是大二学生，不吃辣（1）'), findsOneWidget);
  });

  testWidgets('search and category filter', (tester) async {
    final more = [for (var k = 0; k < 3; k++) mem('x$k', '其他事 $k', 'general')];
    final api = FakeApi([...sample, ...more]);
    await pump(tester, api);
    expect(find.text('全部 7'), findsOneWidget);
    expect(find.text('记得 7 件事 · 4 个分类'), findsOneWidget);
    await tester.tap(find.text('饮食 2'));
    await tester.pumpAndSettle();
    expect(find.text('周末喜欢爬山'), findsNothing);
    expect(find.text('喜欢吃甜的'), findsOneWidget);

    await tester.enterText(find.byType(TextField), '爬山');
    await tester.pumpAndSettle();
    expect(find.text('没有匹配的记忆'), findsOneWidget);
    await tester.tap(find.text('清除筛选'));
    await tester.pumpAndSettle();
    expect(find.text('周末喜欢爬山'), findsOneWidget);
    expect(find.text('不吃辣'), findsOneWidget);
  });

  testWidgets('few memories: no search box, section counts', (tester) async {
    final api = FakeApi([...sample]);
    await pump(tester, api);
    expect(find.byType(TextField), findsNothing); // 不到 memorySearchFrom 条不显示搜索
    expect(find.text('记得 4 件事 · 3 个分类'), findsOneWidget);
    expect(find.text('2'), findsOneWidget); // 饮食分组的数量
  });

  testWidgets('empty: starter opens the add form prefilled', (tester) async {
    final api = FakeApi([]);
    await pump(tester, api);
    expect(find.text('还没有记忆'), findsWidgets);
    expect(find.text('我对你的了解'), findsNothing);
    await tester.tap(find.text('饮食忌口'));
    await tester.pumpAndSettle();
    expect(find.text('新增记忆'), findsOneWidget);
    expect(find.widgetWithText(TextField, '我不吃'), findsOneWidget);
    final food = tester.widget<ChoiceChip>(find.widgetWithText(ChoiceChip, '饮食'));
    expect(food.selected, true);
  });

  test('memorySummary', () {
    expect(memorySummary([]), '还没有记忆');
    expect(memorySummary([MemoryItem.fromJson(mem('a', 'x', 'food'))]), '记得 1 件事');
  });

  testWidgets('old server without digest endpoint hides the card', (tester) async {
    final api = FakeApi([...sample], digestMissing: true);
    await pump(tester, api);
    expect(find.text('我对你的了解'), findsNothing);
    expect(find.text('不吃辣'), findsOneWidget);
  });
}
