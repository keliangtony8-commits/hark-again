// Home 卡片稍后提醒：snoozed_until 解析；卡上“稍后提醒”→ 选时刻 → PATCH（UTC）+ 刷新收件箱；
// SnoozedCards：没有就不占位，有则显示条数与最早时刻，点一条 → PATCH null 放回。
import 'package:assistant/core/api.dart';
import 'package:assistant/features/home/action_card.dart';
import 'package:assistant/features/home/card_snooze.dart';
import 'package:assistant/models/resources.dart';
import 'package:assistant/models/time_shortcuts.dart';
import 'package:assistant/theme/app_theme.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

Map<String, dynamic> cardJson({String id = 'k1', String title = '回复老师邮件', String? snoozed}) => {
      'id': id,
      'kind': 'action',
      'title': title,
      'blocks': [],
      'dismissed': false,
      'unread': snoozed == null,
      'snoozed_until': snoozed,
    };

class FakeApi implements Api {
  final calls = <String>[];
  final bodies = <Object?>[];

  @override
  Future<dynamic> get(String path) async {
    calls.add('GET $path');
    if (path == '/api/inbox') return {'unread': 0, 'latest': null};
    return <dynamic>[cardJson()];
  }

  @override
  Future<dynamic> patch(String path, [Object? body]) async {
    calls.add('PATCH $path');
    bodies.add(body);
    return {...cardJson(), ...(body as Map<String, dynamic>)};
  }

  @override
  dynamic noSuchMethod(Invocation i) => throw UnimplementedError();
}

Future<FakeApi> pump(WidgetTester tester, Widget child) async {
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  final api = FakeApi();
  await tester.pumpWidget(ProviderScope(
    overrides: [apiProvider.overrideWithValue(api)],
    child: MaterialApp(theme: buildTheme(Brightness.light), home: Scaffold(body: Center(child: child))),
  ));
  await tester.pumpAndSettle();
  return api;
}

void main() {
  test('snoozed_until parses to local time', () {
    final c = HomeCard.fromJson(cardJson(snoozed: '2026-10-12T00:00:00+00:00'));
    expect(c.snoozed, isTrue);
    expect(c.snoozedUntil, DateTime.utc(2026, 10, 12).toLocal());
    expect(HomeCard.fromJson(cardJson()).snoozed, isFalse);
    expect(HomeCard.fromJson({...cardJson()}..remove('snoozed_until')).snoozed, isFalse, reason: '老服务端');
  });

  testWidgets('稍后提醒 → pick shortcut → PATCH utc + inbox refresh', (tester) async {
    final api = await pump(tester, ActionCard(card: HomeCard.fromJson(cardJson()), onDo: (_) {}, onOpen: (_, _, {projectId}) {}));
    await tester.tap(find.byTooltip('稍后提醒'));
    await tester.pumpAndSettle();
    expect(find.text('明早 08:00'), findsOneWidget);
    await tester.tap(find.text('明早 08:00'));
    await tester.pumpAndSettle();
    expect(api.calls, containsAllInOrder(['PATCH /api/cards/k1', 'GET /api/inbox']));
    final sent = DateTime.parse((api.bodies.single as Map)['snoozed_until'] as String);
    expect(sent.isUtc, isTrue);
    final expected = onceShortcuts(DateTime.now()).firstWhere((s) => s.$1 == '明早 08:00').$2;
    expect(sent, expected.toUtc());
    expect(find.textContaining('再提醒你'), findsOneWidget);
  });

  testWidgets('SnoozedCards: hidden when empty', (tester) async {
    await pump(tester, const SnoozedCards(cards: []));
    expect(find.textContaining('稍后提醒'), findsNothing);
  });

  testWidgets('SnoozedCards: count + earliest, tap one → put back', (tester) async {
    final now = DateTime(2026, 10, 11, 16);
    final cards = [
      HomeCard(id: 'a', kind: 'action', title: '交水费', blocks: const [], dismissed: false, snoozedUntil: DateTime(2026, 10, 12, 20)),
      HomeCard(id: 'b', kind: 'action', title: '回复老师邮件', blocks: const [], dismissed: false, snoozedUntil: DateTime(2026, 10, 12, 8)),
    ];
    final api = await pump(tester, SnoozedCards(cards: cards, now: now));
    expect(find.text('2 条稍后提醒 · 最早 明天 08:00'), findsOneWidget);
    await tester.tap(find.text('2 条稍后提醒 · 最早 明天 08:00'));
    await tester.pumpAndSettle();
    expect(find.text('点一条，现在放回主页'), findsOneWidget);
    await tester.tap(find.text('交水费 · 明天 20:00'));
    await tester.pumpAndSettle();
    expect(api.calls, contains('PATCH /api/cards/a'));
    expect(api.bodies.single, {'snoozed_until': null});
  });
}
