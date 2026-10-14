// 两步验证（v2.58）：纯规则（解析、文字、码清洗）+ 安全页：没开 → 打开 → 扫码弹层（二维码画出来、秘钥可复制）
// → 码不够 6 位按钮不可点 → 错码显示服务器原话 → 对码后恢复码弹层 → 页面变“已开”；已开时恢复码快用完有警示，
// 关闭走密码 + 码表单并 POST；恢复码弹层写明退出了几台别的设备（v2.61）；二维码固定黑码白底（深色模式也不反色）。
import 'package:assistant/core/api.dart';
import 'package:assistant/core/session.dart';
import 'package:assistant/features/me/security_screen.dart';
import 'package:assistant/models/two_factor.dart';
import 'package:assistant/theme/app_theme.dart';
import 'package:assistant/theme/tokens.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

class _SignedIn extends SessionNotifier {
  @override
  Future<Session> build() async => const Session(server: 'https://me.example', token: 't');
}

class FakeApi implements Api {
  FakeApi({this.enabled = false, this.left = 8});
  bool enabled;
  int left;
  final calls = <String>[];

  Map<String, dynamic> get _status =>
      {'enabled': enabled, 'enabled_at': enabled ? '2026-10-14T00:00:00Z' : null, 'recovery_left': enabled ? left : 0, 'pending': false};

  @override
  Future<dynamic> get(String path) async {
    calls.add('GET $path');
    if (path == '/api/auth/2fa') return _status;
    if (path == '/api/auth/sessions') return {'sessions': []};
    throw UnimplementedError(path);
  }

  @override
  Future<dynamic> post(String path, [Object? body]) async {
    calls.add('POST $path ${body ?? ''}');
    switch (path) {
      case '/api/auth/2fa/setup':
        return {'secret': 'ABCD EFGH IJKL', 'uri': 'otpauth://totp/x?secret=ABCDEFGHIJKL', 'account': 'u',
          'qr': ['10101', '01010', '10101', '01010', '10101']};
      case '/api/auth/2fa/enable':
        if ((body as Map)['code'] != '123456') throw ApiError('验证码不对，看一下验证器里最新的 6 位码', 400);
        enabled = true;
        return {..._status, 'recovery_codes': ['aaaa-bbbb', 'cccc-dddd'], 'signed_out': 2};
      case '/api/auth/2fa/disable':
        enabled = false;
        return _status;
    }
    throw UnimplementedError(path);
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
    child: MaterialApp(theme: buildTheme(b), home: const SecurityScreen()),
  ));
  await tester.pumpAndSettle();
}

void main() {
  test('rules', () {
    final s = TwoFactorStatus.fromJson({'enabled': true, 'enabled_at': '2026-10-14T00:00:00Z', 'recovery_left': 2, 'pending': false});
    expect((s.enabled, s.recoveryLeft, s.enabledAt != null), (true, 2, true));
    expect(twoFactorSummary(s), '两步验证已开');
    expect(twoFactorRowSubtitle(s), '已开 · 恢复码只剩 2 个');
    expect(twoFactorRowSubtitle(null), '登录时多一道验证码');
    expect(twoFactorRowSubtitle(const TwoFactorStatus(enabled: false)), '没开 · 登录只要密码');
    expect(twoFactorRowSubtitle(const TwoFactorStatus(enabled: true, recoveryLeft: 8)), '已开 · 登录要验证码');
    expect(recoveryLine(0), contains('用完'));
    expect(recoveryLine(1), contains('只剩 1 个'));
    expect(recoveryLine(8), contains('还剩 8 个'));
    expect(cleanCode(' １２３ ４５６ '), '123456');
    expect(cleanCode('abcd-efgh'), 'abcd-efgh');
    expect(looksLikeTotp('１２３４５６'), true);
    expect(looksLikeTotp('12345'), false);
    expect(looksLikeTotp('abcd-efgh'), false);
    expect(recoveryCodesText(['a', 'b'], account: 'u'), allOf(contains('（u）'), endsWith('a\nb')));
    final setup = TwoFactorSetup.fromJson({'secret': 'A', 'uri': 'otpauth://', 'account': 'u', 'qr': ['10', '01']});
    expect(setup.drawable, true);
    expect(TwoFactorSetup.fromJson({'qr': ['10', '0']}).drawable, false);
    expect(TwoFactorSetup.fromJson({'qr': ['1x', '01']}).drawable, false);
  });

  testWidgets('enable flow: qr, wrong code shows reason, recovery codes, page flips to on', (tester) async {
    final api = FakeApi();
    await pump(tester, api);
    expect(find.text('两步验证没开'), findsOneWidget);
    await tester.tap(find.byKey(const Key('tf-enable')));
    await tester.pumpAndSettle();
    expect(find.byType(QrMatrix), findsOneWidget);
    expect(find.text('ABCD EFGH IJKL'), findsOneWidget);
    expect(find.byKey(const Key('tf-open-app')), findsOneWidget);
    FilledButton confirm() => tester.widget<FilledButton>(find.byKey(const Key('tf-confirm')));
    expect(confirm().onPressed, isNull);
    await tester.enterText(find.byKey(const Key('tf-code')), '111111');
    await tester.pump();
    expect(confirm().onPressed, isNotNull);
    await tester.tap(find.byKey(const Key('tf-confirm')));
    await tester.pumpAndSettle();
    expect(find.textContaining('验证码不对'), findsOneWidget);
    await tester.enterText(find.byKey(const Key('tf-code')), '123 456');
    await tester.pump();
    await tester.tap(find.byKey(const Key('tf-confirm')));
    await tester.pumpAndSettle();
    expect(api.calls, contains('POST /api/auth/2fa/enable {code: 123456}'));
    expect(find.text('aaaa-bbbb'), findsOneWidget);
    expect(find.text('为了安全，已退出其他 2 台设备'), findsOneWidget); // v2.61 打开 = 退出其他设备
    await tester.tap(find.text('我已存好'));
    await tester.pumpAndSettle();
    expect(find.text('两步验证已开'), findsOneWidget);
    expect(find.byKey(const Key('tf-disable')), findsOneWidget);
  });

  testWidgets('enabled: low recovery warning, disable needs password + code', (tester) async {
    final api = FakeApi(enabled: true, left: 1);
    await pump(tester, api);
    expect(find.textContaining('快用完了', findRichText: true), findsOneWidget);
    await tester.tap(find.byKey(const Key('tf-disable')));
    await tester.pumpAndSettle();
    final fields = find.byType(TextField);
    expect(fields, findsNWidgets(2));
    await tester.enterText(fields.at(0), 'p');
    await tester.enterText(fields.at(1), '654321');
    await tester.pump();
    await tester.tap(find.widgetWithText(FilledButton, '关闭'));
    await tester.pumpAndSettle();
    expect(api.calls.where((c) => c.startsWith('POST /api/auth/2fa/disable')).single, contains('654321'));
    expect(find.text('两步验证没开'), findsOneWidget);
  });

  testWidgets('qr stays black on white in dark mode', (tester) async {
    await tester.pumpWidget(MaterialApp(theme: buildTheme(Brightness.dark), home: const Scaffold(body: Center(child: QrMatrix(rows: ['1'])))));
    final paint = tester.widget<CustomPaint>(find.descendant(of: find.byType(QrMatrix), matching: find.byType(CustomPaint)));
    expect(paint.size, const Size.square(QrColors.size));
    expect(QrColors.dark.computeLuminance(), 0);
    expect(QrColors.light.computeLuminance(), 1);
  });
}
