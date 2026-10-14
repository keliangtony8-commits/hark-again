// 钱包（v2.74）：纯规则（分组、卡组织、Luhn 银联放宽、有效期、安全码、摘要、卡面补点）+ 输入格式化
// + 钱包页：空 → 起步卡；加卡弹层（卡面随输入换卡组织、填错点保存当格提示、对了才 POST 数字卡号）→ 列表有行（过期行带“已过期”）
// → 点行改名走 PATCH；深色模式也不溢出。
import 'package:assistant/core/api.dart';
import 'package:assistant/core/session.dart';
import 'package:assistant/features/me/wallet_screen.dart';
import 'package:assistant/models/wallet.dart';
import 'package:assistant/theme/app_theme.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

class _SignedIn extends SessionNotifier {
  @override
  Future<Session> build() async => const Session(server: 'https://me.example', token: 't');
}

Map<String, dynamic> _card(String id, String label, {bool expired = false}) => {
      'id': id, 'label': label, 'brand': 'visa', 'brand_name': 'Visa', 'last4': '1111', 'exp': expired ? '01/20' : '09/30',
      'exp_month': 9, 'exp_year': 2030, 'holder': '', 'postal_code': '', 'expired': expired, 'created_at': null, 'last_used_at': null,
    };

class FakeApi implements Api {
  FakeApi([List<Map<String, dynamic>>? start]) : cards = start ?? [];
  final List<Map<String, dynamic>> cards;
  final calls = <String>[];

  @override
  Future<dynamic> get(String path) async {
    calls.add('GET $path');
    if (path == '/api/wallet') return [...cards];
    throw UnimplementedError(path);
  }

  @override
  Future<dynamic> post(String path, [Object? body]) async {
    calls.add('POST $path $body');
    final b = body as Map;
    final c = _card('n${cards.length}', (b['label'] as String).isEmpty ? 'Visa 1111' : b['label'] as String);
    cards.add(c);
    return c;
  }

  @override
  Future<dynamic> patch(String path, Object body) async {
    calls.add('PATCH $path $body');
    final c = cards.firstWhere((x) => path.endsWith(x['id'] as String));
    c['label'] = (body as Map)['label'];
    return c;
  }

  @override
  dynamic noSuchMethod(Invocation i) => throw UnimplementedError();
}

Future<void> pump(WidgetTester tester, FakeApi api, {Brightness b = Brightness.light}) async {
  tester.view.physicalSize = const Size(800, 1800);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(ProviderScope(
    overrides: [sessionProvider.overrideWith(_SignedIn.new), apiProvider.overrideWithValue(api)],
    child: MaterialApp(theme: buildTheme(b), home: const WalletScreen()),
  ));
  await tester.pumpAndSettle();
}

TextEditingValue _fmt(TextInputFormatter f, String old, String text) =>
    f.formatEditUpdate(TextEditingValue(text: old), TextEditingValue(text: text));

void main() {
  test('rules', () {
    expect(groupCardNumber('4111111111111111'), '4111 1111 1111 1111');
    expect(groupCardNumber('378282246310005'), '3782 822463 10005');
    expect(groupCardNumber('41111'), '4111 1');
    expect([for (final n in ['4111', '5500', '2221', '3782', '6212', '3530', '6011', '3600', '9999', '']) cardBrand(n)],
        ['visa', 'mastercard', 'mastercard', 'amex', 'unionpay', 'jcb', 'discover', 'diners', 'card', 'card']);
    expect(cardNumberError('4111 1111 1111 1111'), isNull);
    expect(cardNumberError('4111 1111 1111 1112'), contains('校验'));
    expect(cardNumberError('6212345678901234'), isNull); // 银联放宽
    expect(cardNumberError('4111'), contains('位数'));
    final now = DateTime(2026, 10, 14);
    expect(parseExpiry('09/28'), (9, 2028));
    expect(parseExpiry('0928'), (9, 2028));
    expect(parseExpiry('9/2028'), (9, 2028));
    expect(parseExpiry('13/28'), isNull);
    expect(expiryError('10/26', now: now), isNull);
    expect(expiryError('09/26', now: now), contains('过期'));
    expect(expiryError('01/60', now: now), contains('年份'));
    expect(expiryError('x', now: now), contains('月/年'));
    expect(cvcError('123', 'visa'), isNull);
    expect(cvcError('123', 'amex'), contains('4 位'));
    expect(cvcError('1234', 'card'), isNull);
    expect(walletSummary([]), '还没有卡');
    final a = PaymentCardItem.fromJson(_card('a', 'A')), b = PaymentCardItem.fromJson(_card('b', 'B', expired: true));
    expect(walletSummary([a, b]), '2 张卡 · 1 张已过期');
    expect(a.line, 'Visa •••• 1111 · 有效期 09/30');
    expect(CardFace.masked('', 'card'), '•••• •••• •••• ••••');
    expect(CardFace.masked('41111', 'visa'), '4111 1••• •••• ••••');
    expect(CardFace.masked('3782', 'amex'), '3782 •••••• •••••');
  });

  test('formatters', () {
    expect(_fmt(CardNumberFormatter(), '', '4111111111111111999999').text, '4111 1111 1111 1111 999');
    expect(_fmt(ExpiryFormatter(), '', '9').text, '09/');
    expect(_fmt(ExpiryFormatter(), '', '0928').text, '09/28');
    expect(_fmt(ExpiryFormatter(), '09/', '09').text, '09'); // 删到 “/” 前不再自动补回
    expect(_fmt(ExpiryFormatter(), '', '1').text, '1');
  });

  testWidgets('empty → add card → list → rename', (tester) async {
    final api = FakeApi();
    await pump(tester, api);
    expect(find.text('钱包是空的'), findsOneWidget);
    expect(find.text('还没有卡'), findsOneWidget);
    await tester.tap(find.text('添加付款卡').first);
    await tester.pumpAndSettle();
    expect(find.text('新卡'), findsOneWidget);
    expect(find.text('银行卡'), findsOneWidget);
    final fields = find.byType(TextField);
    await tester.enterText(fields.at(0), '4111111111111112');
    await tester.enterText(fields.at(1), '0930');
    await tester.enterText(fields.at(2), '123');
    await tester.enterText(fields.at(5), '招行信用卡');
    await tester.pumpAndSettle();
    expect(find.text('Visa'), findsOneWidget); // 卡面换了卡组织
    expect(find.text('招行信用卡'), findsNWidgets(2));
    await tester.tap(find.text('加密保存'));
    await tester.pumpAndSettle();
    expect(find.textContaining('校验没通过'), findsOneWidget);
    expect(api.calls.where((c) => c.startsWith('POST')), isEmpty);
    await tester.enterText(fields.at(0), '4111111111111111');
    await tester.pumpAndSettle();
    await tester.tap(find.text('加密保存'));
    await tester.pumpAndSettle();
    final post = api.calls.firstWhere((c) => c.startsWith('POST'));
    expect(post, allOf(contains('number: 4111111111111111'), contains('exp_month: 9'), contains('exp_year: 2030'), contains('label: 招行信用卡')));
    expect(find.text('1 张卡'), findsOneWidget);
    expect(find.text('Visa •••• 1111 · 有效期 09/30'), findsOneWidget);
    await tester.tap(find.text('招行信用卡'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('改名'));
    await tester.pumpAndSettle();
    await tester.enterText(find.byType(TextField).last, '工资卡');
    await tester.tap(find.text('保存'));
    await tester.pumpAndSettle();
    expect(api.calls.last, contains('PATCH /api/wallet/n0'));
    expect(find.text('工资卡'), findsOneWidget);
  });

  testWidgets('expired row + dark mode', (tester) async {
    await pump(tester, FakeApi([_card('a', '旧卡', expired: true)]), b: Brightness.dark);
    expect(find.textContaining('已过期'), findsWidgets);
    expect(tester.takeException(), isNull);
  });
}
