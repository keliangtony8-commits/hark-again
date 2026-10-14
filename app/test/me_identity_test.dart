// v0.88 “我的”页页头身份行 + 用量页空月份：
// 取到用户名 → “用户名 · 域名”；老服务器（/api/auth/me 失败）→ 只显示域名；本月零调用 → 说明卡、不画每日图。
import 'package:assistant/core/api.dart';
import 'package:assistant/core/session.dart';
import 'package:assistant/features/me/me_screen.dart';
import 'package:assistant/features/me/usage_chart.dart';
import 'package:assistant/features/me/usage_screen.dart';
import 'package:assistant/models/usage.dart';
import 'package:assistant/theme/app_theme.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

class _SignedIn extends SessionNotifier {
  @override
  Future<Session> build() async => const Session(server: 'https://ai.example.com', token: 't');
}

class _Api implements Api {
  _Api({this.me = true, this.idle = false});
  final bool me, idle;
  @override
  Future<dynamic> get(String path) async {
    if (path == '/api/auth/me') {
      if (!me) throw Exception('404');
      return {'username': 'keliang'};
    }
    if (path.startsWith('/api/usage')) {
      return {
        'currency': 'CNY',
        'priced': ['fast'],
        'today': {'calls': idle ? 0 : 3, 'tokens': idle ? 0 : 4200, 'cost': idle ? 0 : 1.5},
        'month': {'calls': idle ? 0 : 40, 'tokens': idle ? 0 : 250000, 'cost': idle ? 0 : 12.0},
        'daily': [
          {'date': '2026-10-01', 'calls': idle ? 0 : 40, 'tokens': idle ? 0 : 250000, 'cost': idle ? 0 : 12.0}
        ],
      };
    }
    return [];
  }

  @override
  dynamic noSuchMethod(Invocation i) => throw UnimplementedError();
}

Future<void> _pump(WidgetTester tester, Widget home, _Api api) async {
  tester.view.devicePixelRatio = 1;
  tester.view.physicalSize = const Size(420, 1600);
  addTearDown(tester.view.reset);
  SharedPreferences.setMockInitialValues({});
  await tester.pumpWidget(ProviderScope(
    overrides: [sessionProvider.overrideWith(_SignedIn.new), apiProvider.overrideWithValue(api)],
    child: MaterialApp(theme: buildTheme(Brightness.light), home: home),
  ));
  await tester.pumpAndSettle();
}

Finder _identity(String label) => find.bySemanticsLabel(label);

void main() {
  testWidgets('页头：用户名大字 + 域名小字', (tester) async {
    await _pump(tester, const MeScreen(), _Api());
    expect(_identity('已登录 keliang，服务器 ai.example.com'), findsOneWidget);
    expect(find.text('keliang'), findsOneWidget);
    expect(find.text('ai.example.com'), findsOneWidget);
  });

  testWidgets('老服务器没有 /api/auth/me：只显示域名', (tester) async {
    await _pump(tester, const MeScreen(), _Api(me: false));
    expect(_identity('服务器 ai.example.com'), findsOneWidget);
    expect(find.text('keliang'), findsNothing);
    expect(find.text('我的'), findsOneWidget);
  });

  testWidgets('本月零调用：说明卡，不画每日图', (tester) async {
    await _pump(tester, const UsageScreen(), _Api(idle: true));
    expect(find.byKey(const Key('usage-idle')), findsOneWidget);
    expect(find.byType(DailyUsageChart), findsNothing);
  });

  testWidgets('有用量：每日图在，没有说明卡', (tester) async {
    await _pump(tester, const UsageScreen(), _Api());
    expect(find.byKey(const Key('usage-idle')), findsNothing);
    expect(find.byType(DailyUsageChart), findsOneWidget);
  });

  test('idle 只看本月', () {
    const r = UsageReport(currency: 'CNY', today: UsagePeriod(), month: UsagePeriod());
    expect(r.idle, isTrue);
    const busy = UsageReport(currency: 'CNY', today: UsagePeriod(), month: UsagePeriod(calls: 1, tokens: 10));
    expect(busy.idle, isFalse);
  });
}
