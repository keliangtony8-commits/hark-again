import 'package:assistant/core/api.dart';
import 'package:assistant/features/me/connector_library.dart';
import 'package:assistant/features/me/connectors_screen.dart';
import 'package:assistant/features/me/vault_screen.dart';
import 'package:assistant/models/resources.dart';
import 'package:assistant/theme/app_theme.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';

Connector c(String id, {bool configured = true, String? account}) =>
    Connector(id: id, name: id, desc: 'd', configured: configured, account: account);
SecretItem sec(String id, {bool login = false}) =>
    SecretItem(id: id, kind: login ? 'login' : 'api_key', name: id, username: login ? 'me' : null, hosts: const ['a.com'], preview: login ? '' : 'wxyz');

class FakeApi implements Api {
  FakeApi(this.data);
  final Map<String, Object> data;

  @override
  Future<dynamic> get(String path) async => data[path] ?? const [];

  @override
  dynamic noSuchMethod(Invocation i) => throw UnimplementedError();
}

Future<void> pump(WidgetTester tester, String path, Widget screen, Map<String, Object> data) async {
  tester.view.devicePixelRatio = 1;
  tester.view.physicalSize = const Size(420, 1400);
  addTearDown(tester.view.reset);
  final router = GoRouter(initialLocation: path, routes: [
    GoRoute(path: path, builder: (_, _) => screen),
    GoRoute(path: '/me/vault', builder: (_, _) => const VaultScreen()),
  ]);
  await tester.pumpWidget(ProviderScope(
    overrides: [apiProvider.overrideWithValue(FakeApi(data))],
    child: MaterialApp.router(theme: buildTheme(Brightness.light), routerConfig: router),
  ));
  await tester.pumpAndSettle();
}

void main() {
  test('sortAccounts：已连接 → 可连接 → 未配置，同组保持顺序', () {
    final list = [c('x', configured: false), c('b'), c('a', account: 'me@a'), c('d'), c('y', configured: false)];
    expect(sortAccounts(list).map((e) => e.id), ['a', 'b', 'd', 'x', 'y']);
  });

  test('摘要与脱敏', () {
    expect(connectorSummary([c('a')], const []), '还没有连接任何服务');
    expect(connectorSummary([c('a', account: 'x'), c('b')], null), '已连接 1 个账户');
    final mcp = [const McpServerItem(id: 'm', name: 'm', url: 'https://m.dev/mcp', hasToken: false)];
    expect(connectorSummary([c('a', account: 'x')], mcp), '已连接 1 个账户 · 1 个 MCP 服务器');
    expect(vaultSummary(const []), '保险箱是空的');
    expect(vaultSummary([sec('k1'), sec('l', login: true), sec('k2')]), '1 个网站登录 · 2 个 API Key');
    expect(secretHint(sec('k')), '••••wxyz');
    expect(secretHint(sec('l', login: true)), 'me');
  });

  testWidgets('连接器页：页头摘要、MCP 为空时起步卡', (tester) async {
    await pump(tester, '/me/connectors', const ConnectorsScreen(), {
      '/api/connectors': [
        {'id': 'github', 'name': 'GitHub', 'desc': '代码', 'configured': false},
        {'id': 'google', 'name': 'Google', 'desc': '邮件', 'configured': true, 'account': 'me@gmail.com'},
      ],
    });
    expect(find.text('已连接 1 个账户'), findsOneWidget);
    expect(find.text('已连接'), findsOneWidget);
    expect(find.text('接入任何 MCP 服务'), findsOneWidget);
    // 已连接的排在未配置的前面
    expect(tester.getTopLeft(find.text('Google')).dy, lessThan(tester.getTopLeft(find.text('GitHub')).dy));
  });

  test('MCP 服务器问题：auth / down / 不认识 / 老服务器不给', () {
    McpServerItem m(Object? problem) => McpServerItem.fromJson({'id': 'm', 'name': 'm', 'url': 'https://m.dev/mcp', 'problem': ?problem});
    expect(m('auth').problemText, '令牌被拒绝');
    expect(m('down').problemText, '连不上');
    expect(m('weird').problemText, isNull);
    expect(m(null).problemText, isNull);
    expect(connectorSummary(const [], [m('down'), m(null)]), '2 个 MCP 服务器 · 1 个需要处理');
  });

  testWidgets('连接器页：连不上的 MCP 服务器行先说问题，带警示图标', (tester) async {
    await pump(tester, '/me/connectors', const ConnectorsScreen(), {
      '/api/connectors/mcp': [
        {'id': 'a', 'name': 'notes', 'url': 'https://notes.dev/mcp', 'has_token': true, 'problem': 'down'},
        {'id': 'b', 'name': 'calc', 'url': 'https://calc.dev/mcp', 'has_token': true},
      ],
    });
    expect(find.text('连不上 · notes.dev'), findsOneWidget);
    expect(find.text('calc.dev'), findsOneWidget);
    expect(find.byIcon(Icons.error_outline_rounded), findsOneWidget);
    expect(find.text('带令牌'), findsOneWidget); // 有问题的那行不再显示“带令牌”
    expect(find.text('2 个 MCP 服务器 · 1 个需要处理'), findsOneWidget);
  });

  testWidgets('保险箱：分组带数量；空时起步按钮直接打开对应表单', (tester) async {
    await pump(tester, '/me/vault', const VaultScreen(), {
      '/api/vault': [
        {'id': '1', 'kind': 'api_key', 'name': 'OpenWeather', 'hosts': ['api.openweathermap.org'], 'preview': 'abcd'},
        {'id': '2', 'kind': 'login', 'name': '教务', 'username': 'stu', 'hosts': ['jwxt.edu.cn'], 'preview': ''},
      ],
    });
    expect(find.text('1 个网站登录 · 1 个 API Key'), findsOneWidget);
    expect(find.text('••••abcd'), findsOneWidget);
    await tester.tap(find.text('OpenWeather'));
    await tester.pumpAndSettle();
    expect(find.text('删除'), findsOneWidget);
  });

  testWidgets('保险箱为空：网站登录起步按钮 → 登录表单', (tester) async {
    await pump(tester, '/me/vault', const VaultScreen(), const {});
    expect(find.text('保险箱是空的'), findsWidgets);
    await tester.tap(find.text('网站登录'));
    await tester.pumpAndSettle();
    expect(find.text('新网站登录'), findsOneWidget);
    expect(find.text('用户名 / 手机号 / 邮箱'), findsOneWidget);
  });
}
