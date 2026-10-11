// 本月用量 CSV：表头 + 汇总（含上月同期/全月）/每天/模型/对话 四类行；没定价花费留空；未定价模型那行留空；
// 引号/逗号转义、防公式注入、BOM；文件名按报表月份；用量页右上角导出按钮加载完才可点。
import 'dart:async';

import 'package:assistant/core/api.dart';
import 'package:assistant/features/me/usage_screen.dart';
import 'package:assistant/models/usage.dart';
import 'package:assistant/models/usage_csv.dart';
import 'package:assistant/theme/app_theme.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

Map<String, dynamic> body({List<String> priced = const ['fast'], double? budget = 50}) => {
      'currency': 'CNY',
      'budget': budget,
      'priced': priced,
      'today': {'calls': 1, 'tokens': 100, 'cost': 0.0012, 'models': []},
      'month': {
        'calls': 3,
        'tokens': 1300,
        'cost': 3.5,
        'models': [
          {'model': 'fast', 'calls': 2, 'prompt_tokens': 800, 'completion_tokens': 200, 'cost': 3.5},
          {'model': 'local', 'calls': 1, 'prompt_tokens': 250, 'completion_tokens': 50, 'cost': 0},
        ],
      },
      'daily': [
        {'date': '2026-10-01', 'calls': 2, 'tokens': 1200, 'cost': 3.4988},
        {'date': '2026-10-02', 'calls': 1, 'tokens': 100, 'cost': 0.0012},
      ],
      'conversations': [
        {'id': 'a', 'title': '论文, "初稿"', 'calls': 2, 'tokens': 1000, 'cost': 3},
        {'id': 'b', 'title': '=HYPERLINK("x")', 'calls': 1, 'tokens': 100, 'cost': 0.5},
        {'id': 'gone', 'title': null, 'calls': 0, 'tokens': 200, 'cost': 0},
      ],
    };

List<String> lines(String csv) => csv.substring(1).trimRight().split('\r\n');

class _Api implements Api {
  _Api(this.result);
  final Future<dynamic> result;
  @override
  Future<dynamic> get(String path) => result;
  @override
  dynamic noSuchMethod(Invocation i) => throw UnimplementedError();
}

void main() {
  test('有定价：四类行 + 预算 + 转义', () {
    final csv = usageCsv(UsageReport.fromJson(body()));
    expect(csv.startsWith('\uFEFF'), true);
    expect(csv.endsWith('\r\n'), true);
    expect(lines(csv), [
      '类别,名称,日期,调用次数,输入 token,输出 token,总 token,花费（CNY）',
      '汇总,本月,,3,1050,250,1300,3.5',
      '汇总,今天,,1,,,100,0.0012',
      '汇总,预算,,,,,,50',
      '每天,,2026-10-01,2,,,1200,3.4988',
      '每天,,2026-10-02,1,,,100,0.0012',
      '模型,fast,,2,800,200,1000,3.5',
      '模型,local,,1,250,50,300,', // 没定价的模型：花费留空，不写 0
      '对话,"论文, ""初稿""",,2,,,1000,3',
      "对话,\"'=HYPERLINK(\"\"x\"\")\",,1,,,100,0.5", // 防公式注入
      '对话,已删除的对话,,0,,,200,0',
    ]);
  });

  test('没定价：花费整列留空；没预算不出预算行', () {
    final rows = lines(usageCsv(UsageReport.fromJson(body(priced: [], budget: null))));
    expect(rows.any((l) => l.contains('预算')), false);
    for (final l in rows.skip(1)) {
      expect(l.endsWith(','), true, reason: l);
    }
  });

  test('上月同期 + 上月全月：跟在今天后面，输入/输出留空', () {
    final r = UsageReport.fromJson({
      ...body(),
      'last_month': {'calls': 9, 'tokens': 9000, 'cost': 12, 'to_date': {'calls': 4, 'tokens': 2000, 'cost': 2.25}},
    });
    expect(lines(usageCsv(r)).sublist(1, 6), [
      '汇总,本月,,3,1050,250,1300,3.5',
      '汇总,今天,,1,,,100,0.0012',
      '汇总,上月同期,,4,,,2000,2.25',
      '汇总,上月全月,,9,,,9000,12',
      '汇总,预算,,,,,,50',
    ]);
    final unpriced = lines(usageCsv(UsageReport.fromJson({...body(priced: []), 'last_month': {'calls': 1, 'tokens': 5, 'cost': 0, 'to_date': {}}})));
    expect(unpriced.where((l) => l.startsWith('汇总,上月')), ['汇总,上月同期,,0,,,0,', '汇总,上月全月,,1,,,5,']);
  });

  test('老服务器：没有 daily/conversations 也能导出；文件名', () {
    final old = UsageReport.fromJson({...body(), 'daily': null, 'conversations': null});
    expect(lines(usageCsv(old)).where((l) => l.startsWith('每天') || l.startsWith('对话')), isEmpty);
    expect(usageCsvFileName(old, at: DateTime(2026, 3, 9)), '用量-2026-03.csv');
    expect(usageCsvFileName(UsageReport.fromJson(body())), '用量-2026-10.csv');
  });

  testWidgets('导出按钮：加载完才可点', (tester) async {
    final done = Completer<dynamic>();
    await tester.pumpWidget(ProviderScope(
      overrides: [apiProvider.overrideWithValue(_Api(done.future))],
      child: MaterialApp(theme: buildTheme(Brightness.light), home: const UsageScreen()),
    ));
    IconButton btn() => tester.widget<IconButton>(find.byKey(const Key('usage-export')));
    expect(btn().onPressed, isNull);
    done.complete(body());
    await tester.pumpAndSettle();
    expect(btn().onPressed, isNotNull);
    expect(find.byTooltip('导出本月 CSV'), findsOneWidget);
  });
}
