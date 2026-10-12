// 云浏览器按网站保存的登录（v1.26）：models/browser_session.dart 规则 + BrowserSessionsSection（列表、退出确认、空态、出错不画）
// + BrowserBlock 解析 session/site/live。
import 'package:assistant/core/api.dart';
import 'package:assistant/features/computer/browser_sessions_section.dart';
import 'package:assistant/models/block.dart';
import 'package:assistant/models/browser_session.dart';
import 'package:assistant/theme/app_theme.dart';
import 'package:assistant/ui/glass.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

final _now = DateTime.now();
Map<String, dynamic> _list() => {
      'max_open': 1,
      'sessions': [
        {'name': 'taobao-com', 'label': 'taobao.com', 'open': true, 'saved': true,
            'last_used': _now.subtract(const Duration(minutes: 3)).toUtc().toIso8601String(), 'cookies': 3, 'domains': ['taobao.com']},
        {'name': 'main', 'label': '早先的浏览器会话', 'open': false, 'saved': true, 'last_used': null, 'cookies': 1, 'domains': ['x.com']},
      ],
    };

class _Api implements Api {
  _Api(this.body, {this.fail = false});
  Map<String, dynamic> body;
  bool fail;
  final calls = <String>[];
  @override
  Future<dynamic> get(String path) async {
    calls.add('GET $path');
    if (fail) throw ApiError('云浏览器没连上', 503);
    return body;
  }

  @override
  Future<dynamic> delete(String path) async {
    calls.add('DELETE $path');
    return {'ok': true};
  }

  @override
  dynamic noSuchMethod(Invocation i) => throw UnimplementedError();
}

Future<void> _settle(WidgetTester tester) async {
  for (var i = 0; i < 10; i++) {
    await tester.pump(const Duration(milliseconds: 100));
  }
}

Future<_Api> _pump(WidgetTester tester, _Api api) async {
  tester.view.physicalSize = const Size(400, 800);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(ProviderScope(
    overrides: [apiProvider.overrideWithValue(api)],
    child: MaterialApp(
      theme: buildTheme(Brightness.light),
      home: const Scaffold(body: SingleChildScrollView(child: BrowserSessionsSection())),
    ),
  ));
  await _settle(tester);
  return api;
}

void main() {
  test('规则：说明行、行尾、排序、读屏、退出文案', () {
    final list = [for (final x in _list()['sessions'] as List) BrowserSession.fromJson((x as Map).cast<String, dynamic>())];
    final tb = list.first, old = list.last;
    expect(browserSessionDetail(tb, now: _now), '上次用 3 分钟前 · 登录已保存');
    expect(browserSessionHint(tb), '正在用');
    expect(browserSessionHint(old), isNull);
    expect(browserSessionDetail(old), '登录已保存');
    expect(browserSessionDetail(const BrowserSession(name: 'a', label: 'a', saved: true)), '还没有保存的登录');
    expect(browserSessionSemantics(tb, now: _now), 'taobao.com，上次用 3 分钟前 · 登录已保存，正在用');
    expect(browserSignOutText(tb), contains('taobao.com'));
    expect(sortBrowserSessions([old, tb]).map((s) => s.name), ['taobao-com', 'main']);
  });

  test('BrowserBlock：session / site / live；旧卡默认 main', () {
    final b = Block.fromJson({'type': 'browser', 'session': 'taobao-com', 'site': 'taobao.com', 'live': true}) as BrowserBlock;
    expect((b.session, b.site, b.live), ('taobao-com', 'taobao.com', true));
    final o = Block.fromJson({'type': 'browser'}) as BrowserBlock;
    expect((o.session, o.site, o.live), ('main', null, false));
  });

  testWidgets('列表：网站名、说明、正在用；退出先确认，确认后 DELETE 并从列表拿掉', (tester) async {
    final api = await _pump(tester, _Api(_list()));
    expect(find.text('浏览器登录'), findsOneWidget);
    expect(find.text('taobao.com'), findsOneWidget);
    expect(find.text('上次用 3 分钟前 · 登录已保存'), findsOneWidget);
    expect(find.text('正在用'), findsOneWidget);
    expect(find.text('早先的浏览器会话'), findsOneWidget);
    await tester.tap(find.text('退出').first);
    await _settle(tester);
    expect(find.text('退出 taobao.com？'), findsOneWidget);
    await tester.tap(find.descendant(of: find.byType(PillButton), matching: find.text('退出')));
    await _settle(tester);
    expect(api.calls, contains('DELETE /api/browser/sessions/taobao-com'));
    expect(find.text('taobao.com'), findsNothing);
    expect(find.text('早先的浏览器会话'), findsOneWidget);
  });

  test('登录过期（v1.36）：已过期优先于正在用、说明行、读屏', () {
    final s = BrowserSession.fromJson({
      'name': 'jd-com', 'label': 'jd.com', 'open': true, 'saved': true, 'cookies': 2,
      'last_used': _now.subtract(const Duration(minutes: 3)).toUtc().toIso8601String(),
      'signed_in_at': '2026-10-01T08:00:00+00:00', 'expired_at': '2026-10-10T08:00:00+00:00',
    });
    expect(s.expired, isTrue);
    expect(s.signedInAt, isNotNull);
    expect(browserSessionHint(s), '已过期');
    expect(browserSessionDetail(s, now: _now), '上次用 3 分钟前 · $browserSessionExpiredLine');
    expect(browserSessionSemantics(s, now: _now), 'jd.com，上次用 3 分钟前 · $browserSessionExpiredLine');
    final ok = BrowserSession.fromJson({'name': 'a', 'label': 'a', 'signed_in_at': '2026-10-01T08:00:00+00:00', 'expired_at': null});
    expect(ok.expired, isFalse);
  });

  testWidgets('过期的会话：行尾“已过期”警示色、图标换成 public_off', (tester) async {
    final body = _list();
    (body['sessions'] as List).first['expired_at'] = _now.toUtc().toIso8601String();
    await _pump(tester, _Api(body));
    final hint = tester.widget<Text>(find.text('已过期'));
    final ctx = tester.element(find.text('已过期'));
    expect(hint.style?.color, ctx.palette.warning);
    expect(find.text('正在用'), findsNothing);
    expect(find.byIcon(Icons.public_off_rounded), findsOneWidget);
    expect(find.textContaining(browserSessionExpiredLine), findsOneWidget);
  });

  testWidgets('空列表 → 一行说明', (tester) async {
    await _pump(tester, _Api({'sessions': [], 'max_open': 1}));
    expect(find.text(browserSessionsEmpty), findsOneWidget);
    expect(find.text('退出'), findsNothing);
  });

  testWidgets('浏览器服务连不上 → 整节不画', (tester) async {
    await _pump(tester, _Api(_list(), fail: true));
    expect(find.text('浏览器登录'), findsNothing);
  });
}
