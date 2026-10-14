// 助手提议的 Home 建议卡（origin=agent）：解析按钮字/来源、“可以替你做”眉题、主按钮用卡上的字；
// 点了走 POST /api/cards/{id}/start：started → 打开新对话并发指令；不 started → 只打开；卡不收起而是刷新成“已交给助手”；
// 已开始的卡：眉题“已交给助手”、主按钮“查看对话”、次按钮“收起”；系统提醒点“去做”直接发指令，不调 start。
import 'package:assistant/models/resources.dart';
import 'package:flutter_test/flutter_test.dart';

import 'budget_card_test.dart' show FakeApi, cardJson, pump;

Map<String, dynamic> offerJson({String? label = '帮我续费', String? conversation}) => {
      ...cardJson(target: null),
      'title': '续费校园网',
      'blocks': [
        {'type': 'text', 'text': '周五到期，今天续还有 9 折。'}
      ],
      'action_prompt': '去续费校园网一个月',
      'action_label': label,
      'origin': 'agent',
      'conversation_id': conversation,
    };

void main() {
  test('parse label, origin, started', () {
    final c = HomeCard.fromJson(offerJson());
    expect(c.offered, true);
    expect(c.started, false);
    expect(c.actionText, '帮我续费');
    expect(HomeCard.fromJson(offerJson(label: null)).actionText, '去做');
    expect(HomeCard.fromJson(offerJson(label: '  ')).actionText, '去做');
    expect(HomeCard.fromJson(offerJson(conversation: 'c9')).started, true);
    final alert = HomeCard.fromJson({...cardJson(), 'conversation_id': 'c1'});
    expect(alert.offered, false);
    expect(alert.started, false, reason: '系统提醒带对话 id 不算“已开始”');
    expect(alert.actionText, '去做');
  });

  testWidgets('offer card: tap starts on server, opens new conversation with prompt, card stays', (tester) async {
    final sent = <String>[], opened = <(String, String?)>[];
    final api = await pump(tester, offerJson(), sent: sent, opened: opened);
    expect(find.text('可以替你做'), findsOneWidget);
    expect(find.text('去做'), findsNothing);
    await tester.tap(find.text('帮我续费'));
    await tester.pumpAndSettle();
    expect(api.calls, contains('POST /api/cards/k1/start'));
    expect(opened, [('c9', '去续费校园网一个月')]);
    expect(sent, isEmpty, reason: '不走“新对话”的老路');
    expect(api.calls.where((c) => c.startsWith('PATCH')), isEmpty, reason: '不收起');
    expect(api.calls, containsAll(['GET /api/cards', 'GET /api/inbox']));
  });

  testWidgets('started card: eyebrow, 查看对话 reopens without resending, 收起 dismisses', (tester) async {
    final opened = <(String, String?)>[];
    final fake = FakeApi()..startReply = {'conversation_id': 'c9', 'prompt': '去续费校园网一个月', 'started': false};
    final api = await pump(tester, offerJson(conversation: 'c9'), opened: opened, fake: fake);
    expect(find.text('已交给助手 · 查看进展'), findsOneWidget);
    expect(find.text('帮我续费'), findsNothing);
    await tester.tap(find.text('查看对话'));
    await tester.pumpAndSettle();
    expect(opened, [('c9', null)]);
    await tester.tap(find.text('收起'));
    await tester.pumpAndSettle();
    expect(api.calls.any((c) => c.startsWith('PATCH /api/cards/k1') && c.contains('dismissed: true')), true);
  });

  testWidgets('system alert: no eyebrow, 去做 sends prompt, no start call', (tester) async {
    final sent = <String>[];
    final api = await pump(tester, cardJson(unread: false), sent: sent);
    expect(find.text('可以替你做'), findsNothing);
    await tester.tap(find.text('去做'));
    await tester.pumpAndSettle();
    expect(sent, ['看看花在哪']);
    expect(api.calls.where((c) => c.startsWith('PATCH') || c.contains('/start')), isEmpty);
  });
}
