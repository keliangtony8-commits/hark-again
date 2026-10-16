// v2.86 版本管理（home-redesign §K）：名字/版本只来自 lib/brand.dart（brand/sync.py 生成）；
// 版本比较、关于页两段版本、服务器要求更新时“版本”行写“请更新”且“我的 → 关于”行尾提示；老服务器没有 /api/version 照常显示本机版本。
import 'dart:io';

import 'package:assistant/core/cache.dart';
import 'package:assistant/brand.dart';
import 'package:assistant/core/api.dart';
import 'package:assistant/core/session.dart';
import 'package:assistant/features/me/about_screen.dart';
import 'package:assistant/features/me/me_screen.dart';
import 'package:assistant/models/version.dart';
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
  _Api(this.version);
  final Map<String, Object>? version;
  @override
  Future<dynamic> get(String path) async {
    if (path == '/api/version') {
      if (version == null) throw Exception('404');
      return version;
    }
    if (path == '/api/profile') return {'username': 'keliang', 'display_name': null, 'assistant_name': null, 'assistant_default': 'Toyuis', 'avatar': null, 'greet': false};
    if (path.startsWith('/api/usage')) {
      return {'currency': 'CNY', 'priced': [], 'today': {'calls': 0, 'tokens': 0, 'cost': 0}, 'month': {'calls': 0, 'tokens': 0, 'cost': 0}, 'daily': []};
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

void main() {
  test('brand.dart 与仓库唯一来源一致', () {
    final version = File('../VERSION').readAsStringSync().trim();
    expect(appName, 'Toyuis');
    expect(appVersion, version);
    final p = parseVersion(version)!;
    expect(appBuild, p[0] * 10000 + p[1] * 100 + p[2]);
    expect(File('pubspec.yaml').readAsStringSync(), contains('version: $version+$appBuild'));
    expect(File('android/app/src/main/AndroidManifest.xml').readAsStringSync(), contains('android:label="$appName"'));
  });

  test('版本比较', () {
    expect(parseVersion('2.86.0'), [2, 86, 0]);
    expect(parseVersion('v2.86'), isNull);
    expect(versionBelow('2.9.0', '2.86.0'), isTrue); // 数字比，不按字符串
    expect(versionBelow('2.86.1', '2.86.0'), isFalse);
    expect(versionBelow('3.0.0', '2.99.99'), isFalse);
    expect(versionBelow('乱写', '2.0.0'), isFalse); // 解析不了不误报
    final s = ServerVersion.fromJson({'version': '2.90.0', 'min_client': '2.88.0'})!;
    expect(clientOutdated(s, client: '2.86.0'), isTrue);
    expect(clientVersionLabel(s, client: '2.86.0'), '2.86.0 · 请更新');
    expect(clientVersionLabel(s, client: '2.88.0'), '2.88.0');
    expect(clientOutdated(null), isFalse);
    expect(ServerVersion.fromJson({'version': 'dev'}), isNull);
    expect(ServerVersion.fromJson({'version': '2.86.0'})!.minClient, '0.0.0');
  });

  testWidgets('关于：本机版本 + 服务器版本两行', (tester) async {
    await _pump(tester, const AboutScreen(), _Api({'name': 'Toyuis', 'version': '2.85.0', 'build': 28500, 'min_client': '2.0.0'}));
    expect(find.text(appVersion), findsOneWidget);
    expect(find.text('服务器版本'), findsOneWidget);
    expect(find.text('2.85.0'), findsOneWidget);
    expect(find.textContaining('Toyuis 是你自己的私人助手'), findsOneWidget);
  });

  testWidgets('老服务器没有 /api/version：只显示本机版本', (tester) async {
    await _pump(tester, const AboutScreen(), _Api(null));
    expect(find.text(appVersion), findsOneWidget);
    expect(find.text('服务器版本'), findsNothing);
  });

  testWidgets('服务器要求更新：版本行和“我的 → 关于”都提示', (tester) async {
    final api = _Api({'name': 'Toyuis', 'version': '9.0.0', 'build': 90000, 'min_client': '9.0.0'});
    await _pump(tester, const AboutScreen(), api);
    expect(find.text('$appVersion · 请更新'), findsOneWidget);
    await _pump(tester, const MeScreen(), api);
    expect(find.text('请更新'), findsOneWidget);
  });
}
