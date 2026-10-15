import 'package:assistant/core/api.dart';
import 'package:assistant/features/me/connector_library.dart';
import 'package:assistant/features/me/connectors_screen.dart';
import 'package:assistant/features/me/oauth_setup_sheet.dart';
import 'package:assistant/models/resources.dart';
import 'package:assistant/theme/app_theme.dart';
import 'package:assistant/theme/tokens.dart';
import 'package:assistant/ui/glass.dart';
import 'package:assistant/ui/kit.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';

const _setup = ConnectorSetup(console: 'https://github.com/settings/developers', callback: 'https://t.dev/api/oauth/callback',
    env: ['X_CLIENT_ID', 'X_CLIENT_SECRET']);
Connector c(String id, {bool configured = true, String? account}) => Connector(
    id: id, name: id, desc: 'd', account: account, setup: configured ? null : _setup,
    status: account != null ? 'connected' : (configured ? 'available' : 'unconfigured'));
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
  ]);
  await tester.pumpWidget(ProviderScope(
    overrides: [apiProvider.overrideWithValue(FakeApi(data))],
    child: MaterialApp.router(theme: buildTheme(Brightness.light), routerConfig: router),
  ));
  await tester.pumpAndSettle();
}

void main() {
  test('sortAccounts：没配又没连的不画；已连接 → 可连接，同组保持顺序', () {
    final list = [c('x', configured: false), c('b'), c('a', account: 'me@a'), c('d'), c('y', configured: false)];
    expect(sortAccounts(list).map((e) => e.id), ['a', 'b', 'd']);
    expect(missingSetup(list).map((e) => e.id), ['x', 'y']);
    expect(setupLine(missingSetup(list)), '配置 x / y 授权');
    // 连过、但服务器后来删了配置：照样画（账户还在），不算“缺配置”那一行，也不能再授权
    final orphan = Connector(id: 'g', name: 'G', desc: 'd', account: 'me', status: 'connected', setup: _setup);
    expect(sortAccounts([orphan]).single.id, 'g');
    expect(missingSetup([orphan]), isEmpty);
    expect(orphan.authorizable, isFalse);
    expect(c('b').authorizable, isTrue);
  });

  test('ConnectorSetup 解析；缺 status 时宁可当没配', () {
    final j = Connector.fromJson({
      'id': 'github', 'name': 'GitHub', 'status': 'unconfigured',
      'setup': {'console': 'https://github.com/settings/developers', 'callback': 'https://t.dev/api/oauth/callback',
        'env': ['GITHUB_CLIENT_ID', 'GITHUB_CLIENT_SECRET']},
    });
    expect((j.shown, j.authorizable), (false, false));
    expect(j.setup!.env, ['GITHUB_CLIENT_ID', 'GITHUB_CLIENT_SECRET']);
    expect(Connector.fromJson({'id': 'g', 'status': 'available', 'setup': null}).authorizable, isTrue);
    expect(Connector.fromJson({'id': 'g'}).status, 'unconfigured');
    expect(Connector.fromJson({'id': 'g', 'account': 'x'}).status, 'connected');
  });

  test('摘要与脱敏', () {
    expect(connectorSummary([c('a')], const [], const []), '还没有连接任何服务');
    expect(connectorSummary([c('a', account: 'x'), c('b')], null, null), '已连接 1 个账户');
    final mcp = [const McpServerItem(id: 'm', name: 'm', url: 'https://m.dev/mcp', hasToken: false)];
    expect(connectorSummary([c('a', account: 'x')], mcp, const []), '已连接 1 个账户 · 1 个 MCP 服务器');
    expect(connectorSummary(const [], const [], [sec('k1'), sec('l', login: true), sec('k2')]), '3 项加密保存');
    expect(addKinds.map((k) => k.kind), ['mcp', 'login', 'api_key', 'env']);
    expect(secretHint(sec('k')), '••••wxyz');
    expect(secretHint(sec('l', login: true)), 'me');
    const env = SecretItem(id: 'e', kind: 'env', name: 'TG_TOKEN', hosts: [], preview: '');
    expect(groupSecrets([sec('k1'), env]).envs.single.name, 'TG_TOKEN');
    expect(groupSecrets([sec('k1'), env]).keys.length, 1);
    expect(secretHint(env), '');
    expect(secretWhere(env), r'电脑上的命令里读 $TG_TOKEN');
    expect(secretWhere(sec('k')), 'a.com');
    // v2.52：Key 不走默认 Authorization 时副标题说带法
    expect(secretWhere(SecretItem.fromJson({'id': 'q', 'kind': 'api_key', 'name': 'w', 'hosts': ['api.w.com'], 'preview': '1234', 'query_param': 'appid'})),
        'api.w.com · 网址参数 appid');
    expect(secretWhere(SecretItem.fromJson({'id': 'h', 'kind': 'api_key', 'name': 'n', 'hosts': ['api.n.com'], 'preview': '1234', 'header_name': 'x-api-key'})),
        'api.n.com · 请求头 x-api-key');
    expect(secretWhere(SecretItem.fromJson({'id': 'l', 'kind': 'login', 'name': 'l', 'hosts': ['t.com'], 'preview': '', 'header_name': 'x'})), 't.com');
    expect(envName(r' $tg_token '), 'TG_TOKEN');
    expect(envNameError('tg_token'), isNull);
    expect(envNameError('PATH'), contains('系统变量'));
    expect(envNameError('1abc'), isNotNull);
    expect(envNameError('A'), isNotNull);
  });

  const ghSetup = {'console': 'https://github.com/settings/developers', 'callback': 'https://toyuis.itsllm.com/api/oauth/callback',
    'env': ['GITHUB_CLIENT_ID', 'GITHUB_CLIENT_SECRET']};
  const ggSetup = {'console': 'https://console.cloud.google.com/apis/credentials', 'callback': 'https://toyuis.itsllm.com/api/oauth/callback',
    'env': ['GOOGLE_CLIENT_ID', 'GOOGLE_CLIENT_SECRET']};

  testWidgets('连接器页：页头摘要、MCP 为空时起步卡；没配的服务商不画，给部署者一行', (tester) async {
    await pump(tester, '/me/connectors', const ConnectorsScreen(), {
      '/api/connectors': [
        {'id': 'github', 'name': 'GitHub', 'desc': '代码', 'status': 'unconfigured', 'setup': ghSetup},
        {'id': 'google', 'name': 'Google', 'desc': '邮件', 'status': 'connected', 'account': 'me@gmail.com'},
        {'id': 'notion', 'name': 'Notion', 'desc': '笔记', 'status': 'available'},
      ],
    });
    expect(find.text('已连接 1 个账户'), findsOneWidget);
    // 状态是小字（不是胶囊），能连的才有“连接”按钮
    expect(find.widgetWithText(RowHint, '已连接'), findsOneWidget);
    expect(find.widgetWithText(PillButton, '连接'), findsOneWidget);
    expect(tester.getSize(find.widgetWithText(PillButton, '连接')).height, greaterThanOrEqualTo(A11y.minTap));
    expect(find.text('接入更多服务'), findsOneWidget); // MCP 与密钥都空：只有一张起步卡
    expect(find.text('连接的账号'), findsOneWidget);
    // 没配的 GitHub 不画成一行（没有“看起来能点、点了失败”的东西），只在末尾给部署者一行
    expect(find.text('GitHub'), findsNothing);
    expect(find.text('服务器还差一步'), findsOneWidget);
    expect(find.text('配置 GitHub 授权'), findsOneWidget);
    expect(tester.getTopLeft(find.text('Google')).dy, lessThan(tester.getTopLeft(find.text('服务器还差一步')).dy));
  });

  testWidgets('连接器页：一个都没配 → 账户区只有部署者那一行，点开是引导（回调地址、变量名、重启命令）', (tester) async {
    await pump(tester, '/me/connectors', const ConnectorsScreen(), {
      '/api/connectors': [
        {'id': 'google', 'name': 'Google', 'desc': '邮件', 'status': 'unconfigured', 'setup': ggSetup},
        {'id': 'github', 'name': 'GitHub', 'desc': '代码', 'status': 'unconfigured', 'setup': ghSetup},
      ],
    });
    expect(find.byType(PillButton), findsWidgets); // 起步卡的按钮
    expect(find.widgetWithText(PillButton, '连接'), findsNothing);
    expect(find.text('配置 Google / GitHub 授权'), findsOneWidget);
    await tester.tap(find.text('服务器还差一步'));
    await tester.pumpAndSettle();
    expect(find.text('在 Google 开发者后台创建'), findsOneWidget);
    expect(find.text('在 GitHub 开发者后台创建'), findsOneWidget);
    expect(find.text('console.cloud.google.com'), findsOneWidget);
    expect(find.text('https://toyuis.itsllm.com/api/oauth/callback'), findsOneWidget); // 两家同一个回调，只列一次
    expect(find.text('GOOGLE_CLIENT_ID\nGOOGLE_CLIENT_SECRET\nGITHUB_CLIENT_ID\nGITHUB_CLIENT_SECRET'), findsOneWidget);
    expect(find.text(oauthRestartCommand), findsOneWidget);
    expect(find.textContaining('docs/oauth-setup.md'), findsOneWidget);
  });

  testWidgets('连接器页：全部配好 → 没有部署者那一行', (tester) async {
    await pump(tester, '/me/connectors', const ConnectorsScreen(), {
      '/api/connectors': [
        {'id': 'google', 'name': 'Google', 'desc': '邮件', 'status': 'available', 'setup': null},
        {'id': 'github', 'name': 'GitHub', 'desc': '代码', 'status': 'available', 'setup': null},
      ],
    });
    expect(find.widgetWithText(PillButton, '连接'), findsNWidgets(2));
    expect(find.text('服务器还差一步'), findsNothing);
  });

  test('MCP 服务器问题：auth / down / 不认识 / 老服务器不给', () {
    McpServerItem m(Object? problem) => McpServerItem.fromJson({'id': 'm', 'name': 'm', 'url': 'https://m.dev/mcp', 'problem': ?problem});
    expect(m('auth').problemText, '令牌被拒绝');
    expect(m('down').problemText, '无法连接');
    expect(m('weird').problemText, isNull);
    expect(m(null).problemText, isNull);
    expect(connectorSummary(const [], [m('down'), m(null)], null), '2 个 MCP 服务器 · 1 个需要处理');
  });

  test('sortServers：有问题的在前，其余保持顺序', () {
    McpServerItem m(String id, [String? problem]) => McpServerItem.fromJson({'id': id, 'name': id, 'url': 'https://$id.dev', 'problem': ?problem});
    expect(sortServers([m('a'), m('b', 'auth'), m('c'), m('d', 'down')]).map((s) => s.id), ['b', 'd', 'a', 'c']);
  });

  testWidgets('连接器页：连不上的 MCP 服务器行先说问题，带警示图标', (tester) async {
    await pump(tester, '/me/connectors', const ConnectorsScreen(), {
      '/api/connectors/mcp': [
        {'id': 'b', 'name': 'calc', 'url': 'https://calc.dev/mcp', 'has_token': true},
        {'id': 'a', 'name': 'notes', 'url': 'https://notes.dev/mcp', 'has_token': true, 'problem': 'down'},
      ],
    });
    // 有问题的排最前
    expect(tester.getTopLeft(find.text('notes')).dy, lessThan(tester.getTopLeft(find.text('calc')).dy));
    expect(find.text('无法连接 · notes.dev'), findsOneWidget);
    expect(find.text('calc.dev'), findsOneWidget);
    expect(find.byIcon(Icons.error_outline_rounded), findsOneWidget);
    expect(find.text('带令牌'), findsOneWidget); // 有问题的那行不再显示“带令牌”
    expect(find.text('2 个 MCP 服务器 · 1 个需要处理'), findsOneWidget);
  });

  testWidgets('连接的账号一页：账户、MCP、网站登录、API Key 分区同页（v2.96 保险箱并入），有内容就没有起步卡', (tester) async {
    await pump(tester, '/me/connectors', const ConnectorsScreen(), {
      '/api/connectors': [
        {'id': 'google', 'name': 'Google', 'desc': '邮件', 'status': 'connected', 'account': 'me@gmail.com'},
      ],
      '/api/connectors/mcp': [
        {'id': 'b', 'name': 'calc', 'url': 'https://calc.dev/mcp', 'has_token': false},
      ],
      '/api/vault': [
        {'id': '1', 'kind': 'api_key', 'name': 'OpenWeather', 'hosts': ['api.openweathermap.org'], 'preview': 'abcd'},
        {'id': '2', 'kind': 'login', 'name': '教务', 'username': 'stu', 'hosts': ['jwxt.edu.cn'], 'preview': ''},
      ],
    });
    expect(find.text('已连接 1 个账户 · 1 个 MCP 服务器 · 2 项加密保存'), findsOneWidget);
    double y(String t) => tester.getTopLeft(find.text(t)).dy;
    expect(y('Google'), lessThan(y('calc')));
    expect(y('calc'), lessThan(y('教务')));
    expect(y('教务'), lessThan(y('OpenWeather'))); // 网站登录在 API Key 前
    expect(find.text('••••abcd'), findsOneWidget);
    expect(find.text('接入更多服务'), findsNothing);
    expect(find.text('其他服务'), findsNothing); // 不再有跳去另一页的那一行
    await tester.tap(find.text('OpenWeather'));
    await tester.pumpAndSettle();
    expect(find.text('删除'), findsOneWidget);
  });

  testWidgets('连接的账号：环境变量自成一组，点开能换值', (tester) async {
    await pump(tester, '/me/connectors', const ConnectorsScreen(), {
      '/api/vault': [
        {'id': '3', 'kind': 'env', 'name': 'TELEGRAM_BOT_TOKEN', 'hosts': [], 'preview': 'wxyz'},
      ],
    });
    expect(find.text('1 项加密保存'), findsOneWidget);
    expect(find.text('环境变量'), findsOneWidget);
    expect(find.text(r'电脑上的命令里读 $TELEGRAM_BOT_TOKEN'), findsOneWidget);
    expect(find.byIcon(Icons.terminal_rounded), findsOneWidget);
    await tester.tap(find.text('TELEGRAM_BOT_TOKEN'));
    await tester.pumpAndSettle();
    expect(find.text('换个值'), findsOneWidget);
    await tester.tap(find.text('换个值'));
    await tester.pumpAndSettle();
    expect(find.text(r'给 $TELEGRAM_BOT_TOKEN 换个值'), findsOneWidget);
    expect(find.text('变量名'), findsNothing);
  });

  testWidgets('连接的账号为空：起步卡的环境变量 → 变量表单', (tester) async {
    await pump(tester, '/me/connectors', const ConnectorsScreen(), const {});
    await tester.tap(find.widgetWithText(PillButton, '环境变量'));
    await tester.pumpAndSettle();
    expect(find.text('新环境变量'), findsOneWidget);
    expect(find.text('变量名'), findsOneWidget);
  });

  testWidgets('连接的账号为空：起步卡的网站登录 → 登录表单', (tester) async {
    await pump(tester, '/me/connectors', const ConnectorsScreen(), const {});
    await tester.tap(find.widgetWithText(PillButton, '网站登录'));
    await tester.pumpAndSettle();
    expect(find.text('新网站登录'), findsOneWidget);
    expect(find.text('用户名 / 手机号 / 邮箱'), findsOneWidget);
  });

  testWidgets('页头 + 是唯一的添加入口：四类都在，选 MCP 进 MCP 表单', (tester) async {
    await pump(tester, '/me/connectors', const ConnectorsScreen(), {
      '/api/vault': [
        {'id': '1', 'kind': 'api_key', 'name': 'OpenWeather', 'hosts': ['api.openweathermap.org'], 'preview': 'abcd'},
      ],
    });
    expect(find.byTooltip('添加 MCP 服务器'), findsNothing); // MCP 分区不再自带 +
    await tester.tap(find.byTooltip('添加'));
    await tester.pumpAndSettle();
    expect(find.text('添加什么？'), findsOneWidget);
    for (final k in addKinds) {
      expect(find.text('${k.label} · ${k.desc}'), findsOneWidget);
    }
    await tester.tap(find.text('${addKinds.first.label} · ${addKinds.first.desc}'));
    await tester.pumpAndSettle();
    expect(find.text('添加 MCP 服务器'), findsOneWidget);
  });
}
