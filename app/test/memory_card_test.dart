// 聊天里的记忆卡（v0.70）：解析、状态推算（saved/updated/forgotten × 生效/已撤销/对不上/未加载）、
// 撤销真的走记忆资源（DELETE / PATCH 改回 / POST 重建）且卡片随列表变成“已撤销/已恢复”、复制回复不带记忆卡、
// 聊天流里出现记忆卡时记忆列表被重拉。
import 'package:assistant/blocks/block_view.dart';
import 'package:assistant/core/api.dart';
import 'package:assistant/core/resource.dart';
import 'package:assistant/models/block.dart';
import 'package:assistant/models/memory.dart';
import 'package:assistant/models/resources.dart';
import 'package:assistant/theme/app_theme.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

MemoryItem item(String id, String content) => MemoryItem(id: id, content: content, category: 'food');
MemoryBlock card(String action, List<Map<String, dynamic>> items) =>
    Block.fromJson({'type': 'memory', 'action': action, 'items': items}) as MemoryBlock;

class FakeApi implements Api {
  FakeApi(this.memories);
  List<Map<String, dynamic>> memories;
  final calls = <String>[];
  int gets = 0;

  @override
  Future<dynamic> get(String path) async {
    gets++;
    return memories;
  }

  @override
  Future<dynamic> delete(String path) async {
    calls.add('DELETE $path');
    memories = [for (final m in memories) if (m['id'] != path.split('/').last) m];
  }

  @override
  Future<dynamic> patch(String path, [Object? body]) async {
    calls.add('PATCH $path $body');
    final id = path.split('/').last;
    final i = memories.indexWhere((m) => m['id'] == id);
    memories[i] = {...memories[i], ...(body as Map).cast<String, dynamic>()};
    return memories[i];
  }

  @override
  Future<dynamic> post(String path, [Object? body]) async {
    calls.add('POST $path $body');
    final j = {'id': 'new${memories.length}', ...(body as Map).cast<String, dynamic>()};
    memories = [j, ...memories];
    return j;
  }

  @override
  dynamic noSuchMethod(Invocation i) => throw UnimplementedError();
}

Future<void> pump(WidgetTester tester, FakeApi api, MemoryBlock b) async {
  tester.view.physicalSize = const Size(800, 1200);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(ProviderScope(
    overrides: [apiProvider.overrideWithValue(api)],
    child: MaterialApp(theme: buildTheme(Brightness.light), home: Scaffold(body: BlockView(b))),
  ));
  await tester.pumpAndSettle();
}

void main() {
  test('parse + state', () {
    final s = card('saved', [{'id': 'a', 'content': '不吃香菜', 'category': 'food'}]);
    expect(s.items.single.content, '不吃香菜');
    expect(memoryCardState(s, null), MemoryCardState.unknown);
    expect(memoryCardState(s, [item('a', '不吃香菜')]), MemoryCardState.active);
    expect(memoryCardState(s, [item('a', '后来手动改过')]), MemoryCardState.active);
    expect(memoryCardState(s, []), MemoryCardState.undone);

    final u = card('updated', [{'id': 'a', 'content': '能吃微辣', 'category': 'food', 'previous': '不吃辣'}]);
    expect(u.items.single.previous, '不吃辣');
    expect(memoryCardState(u, [item('a', '能吃微辣')]), MemoryCardState.active);
    expect(memoryCardState(u, [item('a', '不吃辣')]), MemoryCardState.undone);
    expect(memoryCardState(u, [item('a', '又改成别的了')]), MemoryCardState.diverged);
    expect(memoryCardState(u, []), MemoryCardState.diverged);

    final f = card('forgotten', [{'id': 'a', 'content': '大二学生'}, {'id': 'b', 'content': '学计算机'}]);
    expect(memoryCardState(f, [item('x', '大二学生')]), MemoryCardState.active);
    expect(memoryCardState(f, [item('x', '大二学生'), item('y', '学计算机')]), MemoryCardState.undone);

    expect(copyText([const TextBlock('好的'), s]), '好的'); // 记忆卡是过程卡，不进剪贴板
  });

  testWidgets('saved → 撤销 = DELETE，卡片变已撤销、内容划掉、撤销键消失', (tester) async {
    final api = FakeApi([{'id': 'a', 'content': '不吃香菜', 'category': 'food'}]);
    await pump(tester, api, card('saved', [{'id': 'a', 'content': '不吃香菜', 'category': 'food'}]));
    expect(find.text('已记住'), findsOneWidget);
    await tester.tap(find.text('撤销'));
    await tester.pumpAndSettle();
    expect(api.calls, ['DELETE /api/memories/a']);
    expect(find.text('已撤销记住'), findsOneWidget);
    expect(find.text('撤销'), findsNothing);
    final t = tester.widget<Text>(find.text('不吃香菜'));
    expect(t.style?.decoration, TextDecoration.lineThrough);
  });

  testWidgets('updated → 显示原来的说法，撤销 = PATCH 改回', (tester) async {
    final api = FakeApi([{'id': 'a', 'content': '能吃微辣', 'category': 'food'}]);
    await pump(tester, api, card('updated', [{'id': 'a', 'content': '能吃微辣', 'category': 'food', 'previous': '不吃辣'}]));
    expect(find.text('已更新记忆'), findsOneWidget);
    expect(find.text('原来：不吃辣'), findsOneWidget);
    await tester.tap(find.text('撤销'));
    await tester.pumpAndSettle();
    expect(api.calls, ['PATCH /api/memories/a {content: 不吃辣}']);
    expect(find.text('已改回原来的说法'), findsOneWidget);
    expect(find.text('原来：不吃辣'), findsNothing);
  });

  testWidgets('forgotten → 恢复 = 逐条 POST 重建', (tester) async {
    final api = FakeApi([]);
    await pump(tester, api, card('forgotten', [{'id': 'a', 'content': '大二学生', 'category': 'profile'}, {'id': 'b', 'content': '学计算机', 'category': 'work'}]));
    expect(find.text('已忘掉'), findsOneWidget);
    await tester.tap(find.text('恢复'));
    await tester.pumpAndSettle();
    expect(api.calls, ['POST /api/memories {content: 大二学生, category: profile}', 'POST /api/memories {content: 学计算机, category: work}']);
    expect(find.text('已恢复'), findsOneWidget);
    expect(find.text('恢复'), findsNothing);
  });

  testWidgets('对不上了 → 只显示，不给撤销', (tester) async {
    final api = FakeApi([{'id': 'a', 'content': '又改了', 'category': 'food'}]);
    await pump(tester, api, card('updated', [{'id': 'a', 'content': '能吃微辣', 'category': 'food', 'previous': '不吃辣'}]));
    expect(find.text('撤销'), findsNothing);
    expect(find.byTooltip('管理记忆'), findsOneWidget);
  });

  test('invalidate 记忆列表会重拉（聊天流收到记忆卡时调用）', () async {
    final api = FakeApi([]);
    final c = ProviderContainer(overrides: [apiProvider.overrideWithValue(api)]);
    addTearDown(c.dispose);
    final sub = c.listen(memoriesProvider, (_, _) {});
    await c.read(memoriesProvider.future);
    api.memories = [{'id': 'a', 'content': '不吃香菜', 'category': 'food'}];
    c.invalidate(memoriesProvider);
    expect((await c.read(memoriesProvider.future)).single.content, '不吃香菜');
    expect(api.gets, 2);
    sub.close();
  });
}
