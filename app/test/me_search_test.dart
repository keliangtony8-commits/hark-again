// v3.0 “我的”页底部设置搜索（docs/devlog.md「2026-10-15 v3.0」）：
// 匹配与排序；两端索引逐字一致、路由都在路由表里、每个定位 id 在两端页面里都真有落点（防止索引和设置页脱节）；
// “我的”页输入即筛 / 没找到 / 清空回原页；点结果带 ?focus= 直达；浮动搜索胶囊不挡最后一项；Spotlight 滚到并闪一下。
import 'dart:io';

import 'package:assistant/core/api.dart';
import 'package:assistant/core/session.dart';
import 'package:assistant/features/me/me_index.dart';
import 'package:assistant/features/me/me_screen.dart';
import 'package:assistant/theme/app_theme.dart';
import 'package:assistant/ui/kit.dart';
import 'package:assistant/ui/motion.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:shared_preferences/shared_preferences.dart';

class _SignedIn extends SessionNotifier {
  @override
  Future<Session> build() async => const Session(server: 'https://ai.example.com', token: 't');
}

class _Api implements Api {
  @override
  String fileUrl(String path) => 'https://ai.example.com$path?token=t';

  @override
  Future<dynamic> get(String path) async {
    if (path == '/api/profile') {
      return {'username': 'keliang', 'display_name': null, 'assistant_name': null, 'assistant_default': 'Toyuis', 'avatar': null, 'greet': false};
    }
    if (path.startsWith('/api/usage')) {
      return {
        'currency': 'CNY',
        'priced': ['fast'],
        'today': {'calls': 3, 'tokens': 4200, 'cost': 1.5},
        'month': {'calls': 40, 'tokens': 250000, 'cost': 12.0},
        'daily': [
          {'date': '2026-10-01', 'calls': 40, 'tokens': 250000, 'cost': 12.0}
        ],
      };
    }
    return [];
  }

  @override
  dynamic noSuchMethod(Invocation i) => throw UnimplementedError();
}

Widget _app({Widget? home, GoRouter? router}) {
  SharedPreferences.setMockInitialValues({});
  final overrides = [sessionProvider.overrideWith(_SignedIn.new), apiProvider.overrideWithValue(_Api())];
  final theme = buildTheme(Brightness.light);
  return ProviderScope(
    overrides: overrides,
    child: router != null ? MaterialApp.router(theme: theme, routerConfig: router) : MaterialApp(theme: theme, home: home),
  );
}

Future<void> _phone(WidgetTester tester, {double bottom = 24}) async {
  tester.view.devicePixelRatio = 2;
  tester.view.physicalSize = const Size(412, 892) * 2;
  tester.view.padding = FakeViewPadding(top: 48, bottom: bottom * 2);
  tester.view.viewPadding = FakeViewPadding(top: 48, bottom: bottom * 2);
  addTearDown(tester.view.reset);
}

Future<void> _type(WidgetTester tester, String text) async {
  await tester.enterText(find.descendant(of: find.byKey(const Key('me-search')), matching: find.byType(TextField)), text);
  await tester.pumpAndSettle();
}

/// meIndex.ts / me_index.dart 里的一条，按同一形状抽出来比对。
typedef _Row = (String id, String title, String section, String route, String? focus, String keywords);

List<_Row> _dartRows(String src) => [
      for (final m in RegExp(r"_e\('([^']*)', '([^']*)', MeSection\.(\w+), '([^']*)', (null|'[^']*'), '([^']*)'\)").allMatches(src))
        (m[1]!, m[2]!, m[3]!, m[4]!, m[5] == 'null' ? null : m[5]!.replaceAll("'", ''), m[6]!),
    ];

List<_Row> _tsRows(String src) => [
      for (final m in RegExp(r'e\("([^"]*)", "([^"]*)", "(\w+)", "([^"]*)", (null|"[^"]*"), "([^"]*)"\)').allMatches(src))
        (m[1]!, m[2]!, m[3]!, m[4]!, m[5] == 'null' ? null : m[5]!.replaceAll('"', ''), m[6]!),
    ];

String _readTree(String dir, String ext) => [
      for (final f in Directory(dir).listSync(recursive: true).whereType<File>().where((f) => f.path.endsWith(ext))) f.readAsStringSync(),
    ].join('\n');

void main() {
  group('匹配', () {
    test('同义词能找到，标题以词开头的排最前', () {
      expect(searchMe('深色').first.id, 'appearance');
      expect(searchMe('外观').first.id, 'appearance'); // 标题命中排在只命中关键词的“偏好设置”前面
      expect(searchMe('外观').map((e) => e.id), contains('preferences'));
      expect(searchMe('2FA').map((e) => e.id).take(2), ['two-factor', 'recovery']); // 不分大小写，同档按索引顺序
      expect(searchMe('退出其他设备').first.id, 'sessions');
    });

    test('多个词都要命中；空查询 / 没有的词返回空', () {
      expect(searchMe('偏好设置 语言').map((e) => e.id), contains('reply-language'));
      expect(searchMe('安全 深色'), isEmpty);
      expect(searchMe('   '), isEmpty);
      expect(searchMe('完全不存在的设置项'), isEmpty);
    });

    test('点了去哪：带定位 id 加 ?focus=', () {
      final appearance = meIndex.firstWhere((e) => e.id == 'appearance');
      expect(appearance.location, '/me/preferences?focus=appearance');
      expect(appearance.where, '偏好设置');
      expect(meIndex.firstWhere((e) => e.id == 'wallet').location, '/me/wallet');
    });
  });

  group('索引不和设置页脱节', () {
    final dart = File('lib/features/me/me_index.dart').readAsStringSync();
    final ts = File('../frontend/src/features/me/meIndex.ts');

    test('两端索引逐字一致（id / 标题 / 分区 / 路由 / 定位 id / 关键词）', () {
      final rows = _dartRows(dart);
      expect(rows.length, meIndex.length, reason: 'me_index.dart 的条目要一行一个 _e(...)，测试按这个形状读');
      if (!ts.existsSync()) return markTestSkipped('没有 frontend/（只拿到 App 时跳过）');
      expect(_tsRows(ts.readAsStringSync()), rows);
    });

    test('每个路由都在 app.dart 的路由表里；带定位的页面套了 SpotlightScope', () {
      final app = File('lib/app.dart').readAsStringSync();
      for (final e in meIndex) {
        final seg = e.route.split('/').last;
        expect(app, contains("path: '$seg'"), reason: '${e.id} 的路由 ${e.route} 不在 app.dart');
        if (e.focus != null) expect(app, contains("path: '$seg', builder: (_, s) => _spot(s,"), reason: '${e.route} 要套 _spot 才能定位');
      }
    });

    test('每个定位 id 在两端页面里都真有落点', () {
      final appSrc = _readTree('lib', '.dart');
      final webDir = Directory('../frontend/src');
      final web = webDir.existsSync() ? _readTree(webDir.path, '.tsx') : null;
      for (final id in {for (final e in meIndex) ?e.focus}) {
        expect(RegExp("Spotlight\\(\\s*id: '$id'").hasMatch(appSrc), isTrue, reason: "App 页面里没有 Spotlight(id: '$id')");
        if (web != null) {
          expect(RegExp('(spot|data-spot)="$id"|<Spot id="$id"').hasMatch(web), isTrue, reason: '网页里没有 spot="$id" / <Spot id="$id">');
        }
      }
    });
  });

  group('“我的”页', () {
    testWidgets('输入即筛：页头保留，原页面换成结果；没找到给说明；清空回原页面', (tester) async {
      await _phone(tester);
      await tester.pumpWidget(_app(home: const MeScreen()));
      await tester.pumpAndSettle();
      expect(find.text('定时任务'), findsOneWidget);

      await _type(tester, '深色');
      expect(find.byKey(const ValueKey('hit-appearance')), findsOneWidget);
      expect(find.text('搜索结果'), findsOneWidget);
      expect(find.text('定时任务'), findsNothing); // 原页面的行收起来了
      expect(find.text('keliang'), findsOneWidget); // 页头还在

      await _type(tester, '完全不存在的设置项');
      expect(find.text('没有找到相关设置'), findsOneWidget);
      expect(find.text('完全不存在的设置项'), findsOneWidget, reason: '只在输入框里，说明文字不回显输入');

      await tester.tap(find.byTooltip('清除'));
      await tester.pumpAndSettle();
      expect(find.text('定时任务'), findsOneWidget);
      expect(find.text('没有找到相关设置'), findsNothing);
    });

    testWidgets('点结果直达：路由带 ?focus=', (tester) async {
      await _phone(tester);
      final router = GoRouter(initialLocation: '/me', routes: [
        GoRoute(path: '/me', builder: (_, _) => const MeScreen(), routes: [
          GoRoute(path: 'preferences', builder: (_, s) => Scaffold(body: Text('focus=${s.uri.queryParameters['focus']}'))),
        ]),
      ]);
      await tester.pumpWidget(_app(router: router));
      await tester.pumpAndSettle();
      await _type(tester, '透明');
      await tester.tap(find.byKey(const ValueKey('hit-solid')));
      await tester.pumpAndSettle();
      expect(find.text('focus=solid'), findsOneWidget);
    });

    for (final (name, bottom) in [('手机含手势条', 24.0), ('无安全区', 0.0)]) {
      testWidgets('浮动搜索胶囊不挡最后一项（$name）：滚到底“退出登录”在胶囊上方', (tester) async {
        await _phone(tester, bottom: bottom);
        tester.view.physicalSize = const Size(412, 560) * 2; // 矮屏：一屏装不下，才有“滚到底”
        await tester.pumpWidget(_app(home: const MeScreen()));
        await tester.pump();
        await tester.pumpAndSettle(); // 第一帧量出胶囊高度，之后按它留白
        await tester.drag(find.byType(ListView), const Offset(0, -20000));
        await tester.pumpAndSettle();
        final last = tester.getRect(find.byKey(const Key('logout')));
        final bar = tester.getRect(find.byKey(const Key('me-search')));
        expect(last.bottom, lessThanOrEqualTo(bar.top), reason: '“退出登录”底边 ${last.bottom} 被搜索胶囊（顶边 ${bar.top}）盖住');
      });
    }
  });

  group('Spotlight 定位', () {
    Widget page(String? focus) => SpotlightScope(
          focus: focus,
          child: Scaffold(
            body: PageBody(children: [
              for (var i = 0; i < 12; i++) Container(height: 200, margin: const EdgeInsets.only(bottom: 16), color: Colors.black12),
              const Spotlight(id: 'far', child: SizedBox(key: Key('far'), height: 64)),
              for (var i = 0; i < 3; i++) Container(height: 200, color: Colors.black12),
            ]),
          ),
        );

    testWidgets('带 focus：屏外很远的那一项也被建出来、滚进视口、闪一下', (tester) async {
      await _phone(tester);
      await tester.pumpWidget(_app(home: page('far')));
      await tester.pumpAndSettle();
      final r = tester.getRect(find.byKey(const Key('far')));
      expect(r.top, greaterThanOrEqualTo(0));
      expect(r.bottom, lessThanOrEqualTo(892));
      final flash = tester.widget<FlashHighlight>(find.ancestor(of: find.byKey(const Key('far')), matching: find.byType(FlashHighlight)));
      expect(flash.play, 1);
    });

    testWidgets('目标区块的数据晚到：内容出来前不闪，出来后才滚到并闪（不闪空边）', (tester) async {
      await _phone(tester);
      final loaded = ValueNotifier(false);
      await tester.pumpWidget(_app(
        home: SpotlightScope(
          focus: 'late',
          child: Scaffold(
            body: PageBody(children: [
              for (var i = 0; i < 8; i++) Container(height: 200, margin: const EdgeInsets.only(bottom: 16), color: Colors.black12),
              Spotlight(
                id: 'late',
                child: ValueListenableBuilder<bool>(
                  valueListenable: loaded,
                  builder: (_, on, _) => on ? const SizedBox(key: Key('late'), height: 64) : const SizedBox.shrink(),
                ),
              ),
            ]),
          ),
        ),
      ));
      await tester.pump(const Duration(milliseconds: 500));
      await tester.pumpAndSettle();
      FlashHighlight flash() => tester.widget<FlashHighlight>(find.byType(FlashHighlight, skipOffstage: false).last);
      expect(flash().play, 0);
      loaded.value = true;
      await tester.pump(const Duration(milliseconds: 200));
      await tester.pumpAndSettle();
      expect(flash().play, 1);
      final r = tester.getRect(find.byKey(const Key('late')));
      expect(r.top, greaterThanOrEqualTo(0));
      expect(r.bottom, lessThanOrEqualTo(892));
    });

    testWidgets('不带 focus：不滚、不多建屏外内容', (tester) async {
      await _phone(tester);
      await tester.pumpWidget(_app(home: page(null)));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('far')), findsNothing); // 还在屏外很远，没被滚过去，也没被提前建出来
    });

    testWidgets('别的 id：目标不闪', (tester) async {
      await _phone(tester);
      await tester.pumpWidget(_app(home: page('other')));
      await tester.pumpAndSettle();
      final flashes = tester.widgetList<FlashHighlight>(find.byType(FlashHighlight, skipOffstage: false));
      expect(flashes, isNotEmpty);
      expect(flashes.every((f) => f.play == 0), isTrue);
    });
  });
}
