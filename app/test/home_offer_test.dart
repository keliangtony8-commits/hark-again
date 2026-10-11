// 助手提议的 Home 建议卡（origin=agent）：解析按钮字/来源、“可以替你做”眉题、主按钮用卡上的字，
// 点了发指令并收起卡（PATCH dismissed + 刷新未读）；系统提醒点“去做”不收起。
import 'package:assistant/models/resources.dart';
import 'package:flutter_test/flutter_test.dart';

import 'budget_card_test.dart' show cardJson, pump;

Map<String, dynamic> offerJson({String? label = '帮我续费'}) => {
      ...cardJson(target: null),
      'title': '续费校园网',
      'blocks': [
        {'type': 'text', 'text': '周五到期，今天续还有 9 折。'}
      ],
      'action_prompt': '去续费校园网一个月',
      'action_label': label,
      'origin': 'agent',
    };

void main() {
  test('parse label and origin', () {
    final c = HomeCard.fromJson(offerJson());
    expect(c.offered, true);
    expect(c.actionText, '帮我续费');
    expect(HomeCard.fromJson(offerJson(label: null)).actionText, '去做');
    expect(HomeCard.fromJson(offerJson(label: '  ')).actionText, '去做');
    final alert = HomeCard.fromJson(cardJson());
    expect(alert.offered, false);
    expect(alert.actionText, '去做');
  });

  testWidgets('offer card: eyebrow, own label, tap sends prompt then dismisses', (tester) async {
    final sent = <String>[];
    final api = await pump(tester, offerJson(), sent: sent);
    expect(find.text('可以替你做'), findsOneWidget);
    expect(find.text('续费校园网'), findsOneWidget);
    expect(find.text('去做'), findsNothing);
    await tester.tap(find.text('帮我续费'));
    await tester.pumpAndSettle();
    expect(sent, ['去续费校园网一个月']);
    expect(api.calls.any((c) => c.startsWith('PATCH /api/cards/k1') && c.contains('dismissed: true')), true);
    expect(api.calls, contains('GET /api/inbox'));
  });

  testWidgets('system alert: no eyebrow, 去做 does not dismiss', (tester) async {
    final sent = <String>[];
    final api = await pump(tester, cardJson(unread: false), sent: sent);
    expect(find.text('可以替你做'), findsNothing);
    await tester.tap(find.text('去做'));
    await tester.pumpAndSettle();
    expect(sent, ['看看花在哪']);
    expect(api.calls.where((c) => c.startsWith('PATCH')), isEmpty);
  });
}
