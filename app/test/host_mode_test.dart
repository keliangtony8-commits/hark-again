// 服务器主机模式（v1.49）：models/host.dart 规则 + 主机命令审批卡（批准范围行、已选一句、危险提示）
// + HostSection（开关先确认 → PUT；没装 → 开关灰掉 + 怎么装；连不上警示；规则列表删除先确认 → DELETE）。
import 'package:assistant/blocks/block_actions.dart';
import 'package:assistant/blocks/block_view.dart';
import 'package:assistant/core/api.dart';
import 'package:assistant/features/computer/host_section.dart';
import 'package:assistant/models/block.dart';
import 'package:assistant/models/host.dart';
import 'package:assistant/theme/app_theme.dart';
import 'package:assistant/ui/glass.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

final _now = DateTime.now();
String _ago(Duration d) => _now.subtract(d).toUtc().toIso8601String();

Map<String, dynamic> _card(String state, {String? granted, bool warn = false}) => {
      'type': 'approval', 'id': 'a1', 'title': '在服务器上运行命令', 'detail': 'systemctl restart nginx', 'state': state,
      'target': 'host', 'host': 'vps-1', 'note': warn ? '会停掉容器' : '改了配置要重启', 'warn': warn,
      'options': warn
          ? [{'id': 'once', 'label': '仅这一次'}]
          : [{'id': 'once', 'label': '仅这一次'}, {'id': 'session', 'label': '这段对话里都允许'},
             {'id': 'rule', 'label': '以后都允许 systemctl restart nginx 开头的命令'}],
      'granted': ?granted,
    };

Map<String, dynamic> _status({bool installed = true, bool enabled = false, bool reachable = true, List rules = const []}) => {
      'installed': installed, 'enabled': enabled, 'reachable': reachable,
      'host': reachable ? {'hostname': 'vps-1', 'os': 'Debian GNU/Linux 12 (bookworm)', 'uptime_seconds': 3 * 86400 + 7200} : null,
      'rules': rules,
    };

final _rule = {'id': 'r1', 'prefix': ['systemctl', 'status'], 'text': 'systemctl status', 'uses': 4,
    'created_at': _ago(const Duration(days: 2)), 'last_used_at': _ago(const Duration(minutes: 3))};

class _Api implements Api {
  _Api(this.body);
  Map<String, dynamic> body;
  final calls = <String>[];
  @override
  Future<dynamic> get(String path) async {
    calls.add('GET $path');
    return body;
  }

  @override
  Future<dynamic> put(String path, Object b) async {
    calls.add('PUT $path ${(b as Map)['enabled']}');
    body = {...body, 'enabled': b['enabled']};
    return body;
  }

  @override
  Future<dynamic> delete(String path) async {
    calls.add('DELETE $path');
    body = {...body, 'rules': []};
    return body;
  }

  @override
  dynamic noSuchMethod(Invocation i) => throw UnimplementedError();
}

Future<void> _settle(WidgetTester tester) async {
  for (var i = 0; i < 10; i++) {
    await tester.pump(const Duration(milliseconds: 100));
  }
}

Future<void> _pumpCard(WidgetTester tester, Map<String, dynamic> j,
    {void Function(String, bool)? onApproval, void Function(String, String)? onOption}) async {
  tester.view.physicalSize = const Size(400, 900);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(MaterialApp(
    theme: buildTheme(Brightness.light),
    home: Scaffold(
      body: BlockActions(
          onApproval: onApproval, onApprovalOption: onOption, child: SingleChildScrollView(child: BlockView(Block.fromJson(j)))),
    ),
  ));
  await _settle(tester);
}

Future<_Api> _pumpSection(WidgetTester tester, _Api api) async {
  tester.view.physicalSize = const Size(400, 900);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(ProviderScope(
    overrides: [apiProvider.overrideWithValue(api)],
    child: MaterialApp(theme: buildTheme(Brightness.light), home: const Scaffold(body: SingleChildScrollView(child: HostSection()))),
  ));
  await _settle(tester);
  return api;
}

void main() {
  test('规则：状态行、开机时长、规则行、批准后一句、读屏', () {
    final s = HostStatus.fromJson(_status(rules: [_rule]));
    expect(hostToggleTitle(s), '主机模式已关闭');
    expect(hostDetail(s), 'vps-1 · Debian GNU/Linux 12 (bookworm) · 已开机 3 天 2 小时');
    expect(hostHint(s), isNull);
    expect(hostDetail(HostStatus.fromJson(_status(installed: false, reachable: false))), '还没装主机代理');
    final down = HostStatus.fromJson(_status(reachable: false));
    expect((hostDetail(down), hostHint(down)), ('连不上主机代理', '连不上'));
    expect(HostStatus.fromJson(_status(installed: false, reachable: false)).canToggle, isFalse);
    expect(hostUptime(59), '1 分钟');
    expect(hostUptime(3 * 3600), '3 小时');
    expect(hostRuleDetail(s.rules.first, now: _now), '放行过 4 次 · 上次 3 分钟前');
    expect(hostRuleDetail(HostRule.fromJson({..._rule, 'uses': 0}), now: _now), '2 天前加的，还没用过');
    final b = Block.fromJson(_card('approved', granted: 'rule')) as ApprovalBlock;
    expect(b.onHost, isTrue);
    expect(approvalGrantedLine(b), '已选：以后都允许 systemctl restart nginx 开头的命令');
    expect(approvalGrantedLine(Block.fromJson(_card('approved', granted: 'once')) as ApprovalBlock), isNull);
    expect(approvalExtraOptions(b).map((o) => o.id), ['session', 'rule']);
    expect(approvalSemantics(b), '在服务器 vps-1上运行：systemctl restart nginx，改了配置要重启，已批准');
    final old = Block.fromJson({'type': 'approval', 'id': 'x', 'title': '需要你批准：删除', 'detail': 'rm -r a', 'state': 'pending'}) as ApprovalBlock;
    expect(old.onHost, isFalse);
    expect(old.options, isEmpty);
    expect(approvalExtraOptions(old), isEmpty);
  });

  testWidgets('主机命令卡：批准 = 仅这一次；范围行带选项批准；没有 onApprovalOption 就不画范围行', (tester) async {
    final replies = <(String, bool)>[], options = <(String, String)>[];
    await _pumpCard(tester, _card('pending'),
        onApproval: (id, ok) => replies.add((id, ok)), onOption: (id, o) => options.add((id, o)));
    expect(find.text('在 vps-1 上，以 root'), findsOneWidget);
    expect(find.text('改了配置要重启'), findsOneWidget);
    expect(find.byIcon(Icons.dns_outlined), findsOneWidget);
    expect(find.text('这段对话里都允许'), findsOneWidget);
    await tester.tap(find.text('以后都允许 systemctl restart nginx 开头的命令'));
    expect(options, [('a1', 'rule')]);
    await tester.tap(find.text('仅这一次'));
    expect(replies, [('a1', true)]);
    await _pumpCard(tester, _card('pending'), onApproval: (id, ok) {});
    expect(find.text('这段对话里都允许'), findsNothing);
    expect(find.text('仅这一次'), findsOneWidget);
  });

  testWidgets('危险提示警示色；批准后按钮收起、显示已选', (tester) async {
    await _pumpCard(tester, _card('pending', warn: true), onApproval: (id, ok) {}, onOption: (id, o) {});
    final ctx = tester.element(find.text('会停掉容器'));
    expect(tester.widget<Text>(find.text('会停掉容器')).style?.color, ctx.palette.warning);
    expect(find.byIcon(Icons.chevron_right_rounded), findsNothing);  // 只有“仅这一次”
    await _pumpCard(tester, _card('approved', granted: 'session'), onApproval: (id, ok) {}, onOption: (id, o) {});
    expect(find.text('已批准'), findsOneWidget);
    expect(find.text('已选：这段对话里都允许'), findsOneWidget);
    expect(find.text('拒绝'), findsNothing);
  });

  testWidgets('开关：打开先确认，确认后 PUT；规则删除先确认', (tester) async {
    final api = await _pumpSection(tester, _Api(_status(rules: [_rule])));
    expect(find.text(hostSectionTitle), findsOneWidget);
    expect(find.text('主机模式已关闭'), findsOneWidget);
    expect(find.text('systemctl status'), findsOneWidget);
    await tester.tap(find.byType(Switch));
    await _settle(tester);
    expect(find.text('打开服务器主机模式？'), findsOneWidget);
    await tester.tap(find.descendant(of: find.byType(PillButton), matching: find.text('打开')));
    await _settle(tester);
    expect(api.calls, contains('PUT /api/host true'));
    expect(find.text('主机模式已打开'), findsWidgets);
    await tester.tap(find.text('删除'));
    await _settle(tester);
    await tester.tap(find.descendant(of: find.byType(PillButton), matching: find.text('删除')));
    await _settle(tester);
    expect(api.calls, contains('DELETE /api/host/rules/r1'));
    expect(find.text(hostRulesEmpty), findsOneWidget);  // 开着、没规则 → 一行说明
  });

  testWidgets('没装主机代理：开关灰掉 + 怎么装；连不上：行尾警示', (tester) async {
    await _pumpSection(tester, _Api(_status(installed: false, reachable: false)));
    expect(tester.widget<Switch>(find.byType(Switch)).onChanged, isNull);
    expect(find.text(hostInstallHint), findsOneWidget);
    expect(find.text(hostRulesEmpty), findsNothing);
  });

  testWidgets('装了但连不上：行尾警示，不提示安装', (tester) async {
    await _pumpSection(tester, _Api(_status(reachable: false)));
    expect(find.text('连不上'), findsOneWidget);
    expect(find.text(hostInstallHint), findsNothing);
  });
}
