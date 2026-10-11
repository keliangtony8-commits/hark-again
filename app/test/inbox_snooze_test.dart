// 收件箱报告“稍后再看”（v1.09）：操作规则（未读才给“标为已读”）；行尾“更多”/长按 → 操作表；
// 稍后再看 → 快捷时刻 → PATCH snoozed_until（UTC）+ 刷新收件箱 + “放回收件箱”提示；标为已读 → POST /api/inbox/read；
// 收起 → PATCH dismissed；SnoozedCards 用“稍后再看”的叫法。
import 'package:assistant/core/api.dart';
import 'package:assistant/features/home/card_snooze.dart';
import 'package:assistant/features/home/report_actions.dart';
import 'package:assistant/models/resources.dart';
import 'package:assistant/theme/app_theme.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

Map<String, dynamic> reportJson({bool unread = true, String? snoozed}) => {
      'id': 'r1',
      'kind': 'report',
      'title': '早报',
      'headline': '今天 · 10月12日',
      'gist': '三件事要留意。',
      'conversation_id': 'c1',
      'blocks': [],
      'dismissed': false,
      'unread': unread,
      'snoozed_until': snoozed,
      'updated_at': '2026-10-12T00:00:00Z',
    };

class FakeApi implements Api {
  final calls = <String>[];
  final bodies = <Object?>[];

  @override
  Future<dynamic> get(String path) async {
    calls.add('GET $path');
    if (path == '/api/inbox') return {'unread': 0, 'latest': null};
    return <dynamic>[reportJson()];
  }

  @override
  Future<dynamic> patch(String path, [Object? body]) async {
    calls.add('PATCH $path');
    bodies.add(body);
    return {...reportJson(), ...(body as Map<String, dynamic>)};
  }

  @override
  Future<dynamic> post(String path, [Object? body]) async {
    calls.add('POST $path');
    bodies.add(body);
    return {'unread': 0, 'latest': null};
  }

  @override
  dynamic noSuchMethod(Invocation i) => throw UnimplementedError();
}

Future<(FakeApi, List<int>)> pump(WidgetTester tester, HomeCard card) async {
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  final api = FakeApi();
  final opened = <int>[];
  await tester.pumpWidget(ProviderScope(
    overrides: [apiProvider.overrideWithValue(api)],
    child: MaterialApp(
      theme: buildTheme(Brightness.light),
      home: Scaffold(body: Center(child: InboxRow(card: card, time: '08:00', onOpen: () => opened.add(1)))),
    ),
  ));
  await tester.pumpAndSettle();
  return (api, opened);
}

void main() {
  test('操作规则：未读才有“标为已读”', () {
    expect(reportActionsOf(HomeCard.fromJson(reportJson())), [ReportAction.snooze, ReportAction.read, ReportAction.dismiss]);
    expect(reportActionsOf(HomeCard.fromJson(reportJson(unread: false))), [ReportAction.snooze, ReportAction.dismiss]);
    expect(snoozeNoun('report'), '稍后再看');
    expect(snoozeNoun('action'), '稍后提醒');
  });

  testWidgets('行：点开打开，摘要显示，更多钮至少 48', (tester) async {
    final (_, opened) = await pump(tester, HomeCard.fromJson(reportJson()));
    expect(find.text('今天 · 10月12日 · 三件事要留意。'), findsOneWidget);
    await tester.tap(find.text('早报'));
    expect(opened, [1]);
    expect(tester.getSize(find.byTooltip('更多')).height, greaterThanOrEqualTo(48));
  });

  testWidgets('稍后再看 → 快捷时刻 → PATCH UTC + 刷新收件箱', (tester) async {
    final (api, _) = await pump(tester, HomeCard.fromJson(reportJson()));
    await tester.tap(find.byTooltip('更多'));
    await tester.pumpAndSettle();
    expect(find.text('标为已读'), findsOneWidget);
    await tester.tap(find.text('稍后再看'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('明早 08:00'));
    await tester.pumpAndSettle();
    expect(api.calls, containsAllInOrder(['PATCH /api/cards/r1', 'GET /api/inbox']));
    final sent = DateTime.parse((api.bodies.single as Map)['snoozed_until'] as String);
    expect(sent.isUtc, isTrue);
    expect(find.textContaining('放回收件箱'), findsOneWidget);
  });

  testWidgets('长按 → 标为已读 → POST read', (tester) async {
    final (api, _) = await pump(tester, HomeCard.fromJson(reportJson()));
    await tester.longPress(find.text('早报'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('标为已读'));
    await tester.pumpAndSettle();
    expect(api.calls, contains('POST /api/inbox/read'));
    expect(api.bodies.last, {'ids': ['r1']});
  });

  testWidgets('收起 → PATCH dismissed', (tester) async {
    final (api, _) = await pump(tester, HomeCard.fromJson(reportJson(unread: false)));
    await tester.tap(find.byTooltip('更多'));
    await tester.pumpAndSettle();
    expect(find.text('标为已读'), findsNothing);
    await tester.tap(find.text('收起'));
    await tester.pumpAndSettle();
    expect(api.bodies.first, {'dismissed': true});
    expect(find.textContaining('已收起'), findsOneWidget);
  });

  testWidgets('SnoozedCards 用“稍后再看”', (tester) async {
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    await tester.pumpWidget(ProviderScope(
      overrides: [apiProvider.overrideWithValue(FakeApi())],
      child: MaterialApp(
        theme: buildTheme(Brightness.light),
        home: Scaffold(
          body: SnoozedCards(
              cards: [HomeCard.fromJson(reportJson(unread: false, snoozed: '2026-10-13T00:00:00Z'))], noun: snoozeNoun('report')),
        ),
      ),
    ));
    await tester.pumpAndSettle();
    expect(find.textContaining('1 条稍后再看'), findsOneWidget);
  });
}
