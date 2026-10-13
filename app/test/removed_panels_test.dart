// v2.17 移除的面板可以找回：removed_at / revivable 解析（老服务端没有 = 不可找回）；removedPanels 只留可找回的、新的在前；
// RemovedPanels 没有就不占位，有则“N 个最近移除的面板”，点开选一个 → POST revive + 提示；
// removePanel → POST remove + “已移除 · 撤销”，点撤销 → POST revive。
import 'package:assistant/core/api.dart';
import 'package:assistant/features/home/removed_panels.dart';
import 'package:assistant/models/resources.dart';
import 'package:assistant/theme/app_theme.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

HomeCard panel(String id, String title, {DateTime? removedAt, bool? revivable, String kind = 'panel'}) => HomeCard(
    id: id, kind: kind, title: title, blocks: const [], dismissed: removedAt != null, removedAt: removedAt, revivable: revivable ?? removedAt != null);

class FakeApi implements Api {
  final calls = <String>[];

  @override
  Future<dynamic> get(String path) async {
    calls.add('GET $path');
    return <dynamic>[];
  }

  @override
  Future<dynamic> post(String path, [Object? body]) async {
    calls.add('POST $path');
    return {'id': 'p1', 'title': '上海天气', 'task_id': 't2', 'revivable': true};
  }

  @override
  dynamic noSuchMethod(Invocation i) => throw UnimplementedError();
}

Future<FakeApi> pump(WidgetTester tester, Widget Function(WidgetRef ref) child) async {
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  final api = FakeApi();
  await tester.pumpWidget(ProviderScope(
    overrides: [apiProvider.overrideWithValue(api)],
    child: MaterialApp(
        theme: buildTheme(Brightness.light),
        home: Scaffold(body: Center(child: Consumer(builder: (_, ref, _) => child(ref))))),
  ));
  await tester.pumpAndSettle();
  return api;
}

void main() {
  test('parse removed_at / revivable; old server = not revivable', () {
    final c = HomeCard.fromJson({
      'id': 'p1', 'kind': 'panel', 'title': '天气', 'blocks': [], 'dismissed': true,
      'removed_at': '2026-10-12T00:00:00+00:00', 'revivable': true,
    });
    expect(c.revivable, isTrue);
    expect(c.removedAt, DateTime.utc(2026, 10, 12).toLocal());
    final old = HomeCard.fromJson({'id': 'p1', 'kind': 'panel', 'title': '天气', 'blocks': [], 'dismissed': true});
    expect(old.revivable, isFalse);
    expect(old.removedAt, isNull);
  });

  test('removedPanels: only revivable panels, newest first', () {
    final out = removedPanels([
      panel('a', '旧的', removedAt: DateTime(2026, 10, 1)),
      panel('b', '新的', removedAt: DateTime(2026, 10, 12)),
      panel('c', '过期', removedAt: DateTime(2026, 9, 1), revivable: false),
      panel('d', '在用'),
      panel('e', '建议', removedAt: DateTime(2026, 10, 12), kind: 'action'),
    ]);
    expect(out.map((c) => c.id), ['b', 'a']);
  });

  testWidgets('RemovedPanels: hidden when empty', (tester) async {
    await pump(tester, (_) => const RemovedPanels(cards: []));
    expect(find.textContaining('最近移除'), findsNothing);
  });

  testWidgets('RemovedPanels: count, tap one → revive', (tester) async {
    final now = DateTime(2026, 10, 13, 15);
    final cards = [panel('p1', '上海天气', removedAt: DateTime(2026, 10, 13, 9))];
    final api = await pump(tester, (_) => RemovedPanels(cards: cards, now: now));
    expect(find.text('1 个最近移除的面板 · 30 天内可找回'), findsOneWidget);
    await tester.tap(find.text('1 个最近移除的面板 · 30 天内可找回'));
    await tester.pumpAndSettle();
    expect(find.text('点一个，放回主页'), findsOneWidget);
    await tester.tap(find.text('上海天气 · 移除于 今天 09:00'));
    await tester.pumpAndSettle();
    expect(api.calls, containsAllInOrder(['POST /api/cards/p1/revive', 'GET /api/cards']));
    expect(find.text('「上海天气」放回来了，正在重新取数据'), findsOneWidget);
  });

  testWidgets('removePanel → POST remove + undo toast → revive', (tester) async {
    final card = panel('p1', '上海天气');
    final api = await pump(
        tester, (ref) => Builder(builder: (ctx) => TextButton(onPressed: () => removePanel(ctx, ref, card), child: const Text('移除'))));
    await tester.tap(find.text('移除'));
    await tester.pumpAndSettle();
    expect(api.calls, containsAllInOrder(['POST /api/cards/p1/remove', 'GET /api/cards']));
    expect(find.text('已移除「上海天气」，30 天内可以找回'), findsOneWidget);
    await tester.tap(find.text('撤销'));
    await tester.pumpAndSettle();
    expect(api.calls, contains('POST /api/cards/p1/revive'));
  });
}
