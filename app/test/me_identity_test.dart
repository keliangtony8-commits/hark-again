// v0.88 “我的”页页头身份行 + 用量页空月份：
// 取到用户名 → “用户名 · 域名”；取不到资料（GET /api/profile 失败）→ 只显示域名；本月零调用 → 说明卡、不画每日图。
// v2.92 §P：有称呼用称呼、头像首字母；点名字打开个人资料弹层，只送改了的字段。
import 'package:assistant/core/cache.dart';
import 'package:assistant/core/api.dart';
import 'package:assistant/core/profile.dart';
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
  _Api({this.me = true, this.idle = false, this.displayName});
  final bool me, idle;
  final String? displayName;
  final patches = <Map<String, dynamic>>[];
  Map<String, dynamic> _profile() => {'username': 'keliang', 'display_name': displayName, 'assistant_name': null, 'assistant_default': 'Toyuis', 'avatar': null, 'greet': false};
  @override
  Future<dynamic> patch(String path, Object body) async {
    patches.add(Map<String, dynamic>.from(body as Map));
    return {..._profile(), ...patches.last};
  }

  @override
  String fileUrl(String path) => 'https://ai.example.com$path?token=t';

  @override
  Future<dynamic> get(String path) async {
    if (path == '/api/profile') {
      if (!me) throw Exception('404');
      return _profile();
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
    overrides: [sessionProvider.overrideWith(_SignedIn.new), apiProvider.overrideWithValue(api), cacheStoreProvider.overrideWithValue(MemoryCacheStore())],
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

  testWidgets('取不到个人资料：只显示域名', (tester) async {
    await _pump(tester, const MeScreen(), _Api(me: false));
    expect(_identity('服务器 ai.example.com'), findsOneWidget);
    expect(find.text('keliang'), findsNothing);
    expect(find.text('我的'), findsOneWidget);
  });

  testWidgets('有称呼：页头用称呼，头像首字母', (tester) async {
    await _pump(tester, const MeScreen(), _Api(displayName: 'tony'));
    expect(_identity('已登录 tony，服务器 ai.example.com'), findsOneWidget);
    expect(find.text('T'), findsOneWidget);
  });

  testWidgets('点名字：个人资料弹层，只送改了的字段', (tester) async {
    final api = _Api();
    await _pump(tester, const MeScreen(), api);
    await tester.tap(find.byKey(const Key('me-identity')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('profile-name')), findsOneWidget);
    await tester.enterText(find.byKey(const Key('profile-assistant')), '小克');
    await tester.tap(find.byKey(const Key('profile-save')));
    await tester.pumpAndSettle();
    expect(api.patches, [{'assistant_name': '小克'}]);
    expect(find.byKey(const Key('profile-name')), findsNothing);
  });

  test('Profile：称呼优先、首字母、助手名默认', () {
    final a = Profile.fromJson({'username': 'keliang', 'display_name': '  ', 'assistant_default': 'Toyuis'});
    expect(a.name, 'keliang');
    expect(a.initial, 'K');
    expect(a.assistant, 'Toyuis');
    final b = Profile.fromJson({'username': 'keliang', 'display_name': '阿亮', 'assistant_name': '小克', 'greet': true});
    expect(b.initial, '阿');
    expect(b.assistant, '小克');
    expect(b.greet, isTrue);
    expect(const Profile(username: '').initial, '我');
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
