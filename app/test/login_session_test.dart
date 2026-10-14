// 登录设备（v2.61）：纯规则（解析、设备名、副标题、提示）+ 安全页“登录设备”区块：本机排第一标“本机”没有退出钮，
// 别的设备退出要确认、发 DELETE、行马上消失；“退出其他所有设备”确认后 POST、只剩本机、提示退了几台；只有本机时没有那一行。
import 'package:assistant/core/api.dart';
import 'package:assistant/core/session.dart';
import 'package:assistant/features/me/security_screen.dart';
import 'package:assistant/models/login_session.dart';
import 'package:assistant/theme/app_theme.dart';
import 'package:assistant/ui/glass.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

class _SignedIn extends SessionNotifier {
  @override
  Future<Session> build() async => const Session(server: 'https://me.example', token: 't');
}

class FakeApi implements Api {
  FakeApi(this.sessions);
  List<Map<String, dynamic>> sessions;
  final calls = <String>[];

  @override
  Future<dynamic> get(String path) async {
    calls.add('GET $path');
    if (path == '/api/auth/2fa') return {'enabled': false, 'recovery_left': 0, 'pending': false};
    if (path == '/api/auth/sessions') return {'sessions': sessions};
    throw UnimplementedError(path);
  }

  @override
  Future<dynamic> delete(String path) async {
    calls.add('DELETE $path');
    sessions = [for (final s in sessions) if ('/api/auth/sessions/${s['id']}' != path) s];
    return {'ok': true, 'current': false};
  }

  @override
  Future<dynamic> post(String path, [Object? body]) async {
    calls.add('POST $path');
    if (path == '/api/auth/sessions/revoke-others') {
      final n = sessions.where((s) => s['current'] != true).length;
      sessions = [for (final s in sessions) if (s['current'] == true) s];
      return {'signed_out': n};
    }
    throw UnimplementedError(path);
  }

  @override
  dynamic noSuchMethod(Invocation i) => throw UnimplementedError();
}

final _now = DateTime.now().toUtc();
Map<String, dynamic> _s(String id, String label, String kind, {bool current = false, int agoMin = 0}) => {
      'id': id, 'label': label, 'kind': kind, 'current': current,
      'created_at': _now.subtract(const Duration(days: 3)).toIso8601String(),
      'last_seen_at': _now.subtract(Duration(minutes: agoMin)).toIso8601String(),
    };

Future<void> pump(WidgetTester tester, FakeApi api) async {
  tester.view.physicalSize = const Size(800, 1800);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(ProviderScope(
    overrides: [sessionProvider.overrideWith(_SignedIn.new), apiProvider.overrideWithValue(api)],
    child: MaterialApp(theme: buildTheme(Brightness.light), home: const SecurityScreen()),
  ));
  await tester.pumpAndSettle();
}

void main() {
  test('rules', () {
    final now = DateTime(2026, 10, 14, 9);
    final list = parseLoginSessions({
      'sessions': [
        {'id': 'a', 'label': 'Chrome · Windows', 'kind': 'browser', 'current': true, 'created_at': DateTime(2026, 10, 14, 8).toIso8601String(),
          'last_seen_at': now.toIso8601String()},
        {'id': 'b', 'label': 'Android App', 'kind': 'app', 'created_at': DateTime(2026, 10, 2).toIso8601String(),
          'last_seen_at': DateTime(2026, 10, 14, 8, 30).toIso8601String()},
        {'id': 'c'},
      ]
    });
    expect(list.length, 3);
    expect(loginSessionLine(list[0], now: now), '这台设备 · 今天登录');
    expect(loginSessionLine(list[1], now: now), '30 分钟前活动 · 10月2日登录');
    expect((list[2].label, list[2].kind, loginSessionLine(list[2], now: now)), ('未知设备', 'other', ''));
    expect(parseLoginSessions(null), isEmpty);
    expect(loginSessionsSummary(list), '3 台设备登着');
    expect(loginSessionsSummary(list.take(1).toList()), '只有这台设备登着');
    expect(appDeviceLabel('android'), 'Android App');
    expect(appDeviceLabel('ios'), 'iPhone App');
    expect(appDeviceLabel('fuchsia'), 'App');
    expect(signedOutToast(0), '没有别的设备登着');
    expect(signedOutToast(2), '已退出其他 2 台设备');
    expect(enabledSignedOutToast(0), isNull);
    expect(enabledSignedOutToast(1), contains('1 台'));
  });

  testWidgets('devices: current first without button, revoke one, revoke others', (tester) async {
    final api = FakeApi([
      _s('web', 'Chrome · Windows', 'browser', current: true),
      _s('phone', 'Android App', 'app', agoMin: 5),
      _s('pc', 'Firefox · Linux', 'browser', agoMin: 120),
    ]);
    await pump(tester, api);
    expect(find.text('登录设备'), findsOneWidget);
    expect(find.text('3 台设备登着'), findsOneWidget);
    expect(find.text('本机'), findsOneWidget);
    expect(find.widgetWithText(TextButton, '退出'), findsNWidgets(2));
    expect(find.textContaining('5 分钟前活动'), findsOneWidget);

    await tester.tap(find.widgetWithText(TextButton, '退出').first);
    await tester.pumpAndSettle();
    expect(find.text('退出 Android App？'), findsOneWidget);
    await tester.tap(find.widgetWithText(PillButton, '退出'));
    await tester.pumpAndSettle();
    expect(api.calls, contains('DELETE /api/auth/sessions/phone'));
    expect(find.text('Android App'), findsNothing);
    expect(find.text('已退出 Android App'), findsOneWidget);

    await tester.tap(find.byKey(const Key('ls-others')));
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(PillButton, '全部退出'));
    await tester.pumpAndSettle();
    expect(api.calls, contains('POST /api/auth/sessions/revoke-others'));
    expect(find.text('Firefox · Linux'), findsNothing);
    expect(find.text('已退出其他 1 台设备'), findsOneWidget);
    expect(find.byKey(const Key('ls-others')), findsNothing);
    expect(find.text('只有这台设备登着'), findsOneWidget);
  });

  testWidgets('only this device: no revoke-others row', (tester) async {
    await pump(tester, FakeApi([_s('web', 'Chrome · Windows', 'browser', current: true)]));
    expect(find.text('Chrome · Windows'), findsOneWidget);
    expect(find.byKey(const Key('ls-others')), findsNothing);
  });
}
