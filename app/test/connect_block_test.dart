// v2.36 连接卡（后端 ConnectBlock / app/connector_accounts.py）：解析；卡上那一行和按钮按连接器列表实时状态定
// （快照 / 可以连 / 已连接 / 换号 / 授权失效 / 没配）；点按钮问服务器要授权地址（?client=app）；连接器 status 老服务器缺省时按账户推。
import 'package:assistant/blocks/block_view.dart';
import 'package:assistant/core/api.dart';
import 'package:assistant/models/block.dart';
import 'package:assistant/models/connect.dart';
import 'package:assistant/models/resources.dart';
import 'package:assistant/theme/app_theme.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

class FakeApi implements Api {
  FakeApi(this.list);
  List<Map<String, dynamic>> list;
  final gets = <String>[];
  @override
  Future<dynamic> get(String path) async {
    gets.add(path);
    if (path == '/api/connectors') return list;
    throw ApiError('服务器还没配置', 400);
  }

  @override
  dynamic noSuchMethod(Invocation i) => throw UnimplementedError();
}

Map<String, dynamic> conn(String status, {String? account}) =>
    {'id': 'google', 'name': 'Google', 'desc': 'Gmail、日历、云端硬盘', 'account': account, 'status': status};

const block = {'type': 'connect', 'provider': 'google', 'name': 'Google', 'desc': 'Gmail、日历、云端硬盘', 'reason': '读你的日历排明天的事'};

Widget host(FakeApi api, Map<String, dynamic> j) => ProviderScope(
      overrides: [apiProvider.overrideWithValue(api)],
      child: MaterialApp(
        theme: buildTheme(Brightness.light),
        home: Scaffold(body: Padding(padding: const EdgeInsets.all(16), child: BlockView(Block.fromJson(j)))),
      ),
    );

void main() {
  final b = Block.fromJson(block) as ConnectBlock;
  final again = Block.fromJson({...block, 'reconnect': true, 'account': 'me@gmail.com'}) as ConnectBlock;

  test('解析与状态', () {
    expect((b.provider, b.reason, b.reconnect, b.account), ('google', '读你的日历排明天的事', false, null));
    expect(again.reconnect, isTrue);
    expect(connectCardState(b, null), (line: 'Gmail、日历、云端硬盘', button: '连接 Google', tone: ConnectTone.action));
    expect(connectCardState(again, null).button, '重新连接');
    Connector c(String s, {String? a}) => Connector.fromJson(conn(s, account: a));
    expect(connectCardState(b, c('available')).button, '连接 Google');
    expect(connectCardState(b, c('connected', a: 'me@gmail.com')), (line: '已连接 · me@gmail.com', button: null, tone: ConnectTone.done));
    expect(connectCardState(again, c('connected', a: 'me@gmail.com')).button, '换个账户');
    expect(connectCardState(b, c('expired', a: 'me@gmail.com')), (line: '授权失效 · me@gmail.com', button: '重新连接', tone: ConnectTone.warning));
    expect(connectCardState(b, c('unconfigured')).button, isNull);
    // v2.90.2：只认 status；服务器后来删了配置（setup 非空）时，失效 / 换号都不给按钮
    final orphan = {...conn('expired', account: 'x'), 'setup': {'console': 'c', 'callback': 'u', 'env': ['A', 'B']}};
    expect(connectCardState(b, Connector.fromJson(orphan)), (line: '授权失效 · x', button: null, tone: ConnectTone.warning));
    expect(connectCardState(again, Connector.fromJson({...orphan, 'status': 'connected'})).button, isNull);
    expect(Connector.fromJson(conn('expired', account: 'x')).expired, isTrue);
  });

  testWidgets('可以连：理由 + 连接按钮，点了问服务器要授权地址', (t) async {
    final api = FakeApi([conn('available')]);
    await t.pumpWidget(host(api, block));
    await t.pumpAndSettle();
    expect(find.text('Google'), findsOneWidget);
    expect(find.text('读你的日历排明天的事'), findsOneWidget);
    await t.tap(find.text('连接 Google'));
    await t.pumpAndSettle();
    expect(api.gets, contains('/api/connectors/google/start?client=app'));
    expect(find.text('服务器还没配置'), findsOneWidget); // 出错 → 吐司
    await t.pump(const Duration(seconds: 5));
  });

  testWidgets('已连接：按钮消失，显示账户；授权失效：重新连接', (t) async {
    await t.pumpWidget(host(FakeApi([conn('connected', account: 'me@gmail.com')]), block));
    await t.pumpAndSettle();
    expect(find.text('已连接 · me@gmail.com'), findsOneWidget);
    expect(find.byType(FilledButton), findsNothing);
    await t.pumpWidget(const SizedBox());
    await t.pumpWidget(host(FakeApi([conn('expired', account: 'me@gmail.com')]), block));
    await t.pumpAndSettle();
    expect(find.text('授权失效 · me@gmail.com'), findsOneWidget);
    expect(find.text('重新连接'), findsOneWidget);
  });
}
