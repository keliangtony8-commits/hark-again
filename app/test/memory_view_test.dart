// 内存去哪了（v1.94）：规则（行文案、占比、快满点名最大的、没在跑 / 没得排不出现）+ 电脑页那一节（行、其它、点任务看日志）。
import 'package:assistant/core/api.dart';
import 'package:assistant/features/computer/computer_details.dart';
import 'package:assistant/models/computer.dart';
import 'package:assistant/theme/app_theme.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

const _mb = 1 << 20;

Map<String, dynamic> _status({int used = 800 * _mb, String state = 'running', bool rows = true}) => {
      'workspace': 'me',
      'sandbox': {'state': state, 'memory_used': used, 'memory_limit': 1024 * _mb},
      'storage': const {},
      'running_jobs': [
        {'id': 'jbig', 'title': '大任务', 'command': 'python big.py', 'state': 'running', 'output_tail': '', 'created_at': '2026-10-13T00:00:00Z'},
      ],
      'memory': {
        'used': used,
        'limit': 1024 * _mb,
        'rows': rows
            ? [
                {'kind': 'job', 'id': 'jbig', 'title': '大任务', 'memory': 350 * _mb, 'processes': 2, 'share': 0.4375},
                {'kind': 'process', 'pid': 9, 'title': '/usr/bin/python3 bot.py', 'memory': 120 * _mb, 'processes': 1, 'share': 0.15},
                {'kind': 'service', 'id': 'svc', 'title': '网站', 'memory': 2 * _mb, 'processes': 1, 'share': 0.0025},
              ]
            : [],
        'other': 328 * _mb,
      },
    };

class _Api implements Api {
  _Api(this.status);
  Map<String, dynamic> status;
  final calls = <String>[];
  @override
  Future<dynamic> get(String path) async {
    calls.add('GET $path');
    if (path.startsWith('/api/jobs/')) return status['running_jobs'][0];
    return status;
  }

  @override
  dynamic noSuchMethod(Invocation i) => throw UnimplementedError();
}

Future<_Api> _pump(WidgetTester tester, Map<String, dynamic> status) async {
  tester.view.physicalSize = const Size(400, 1400);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  final api = _Api(status);
  await tester.pumpWidget(ProviderScope(
    overrides: [apiProvider.overrideWithValue(api)],
    child: MaterialApp(
      theme: buildTheme(Brightness.light),
      home: const Scaffold(body: SingleChildScrollView(child: MemorySection(ws: 'me'))),
    ),
  ));
  for (var i = 0; i < 10; i++) {
    await tester.pump(const Duration(milliseconds: 100));
  }
  return api;
}

void main() {
  test('规则：头一行、行文案、占比、其它、快满点名最大的', () {
    final s = ComputerStatus.fromJson(_status());
    final v = memoryViewOf(s)!;
    expect(memoryViewLine(v), '已用 800.0 MB，上限 1 GB');
    expect(v.tight, isFalse);
    expect(memoryTightNote(v), isNull);
    expect(memoryRowTitle(v.rows[0]), '大任务');
    expect(memoryRowLine(v.rows[0]), '后台任务 · 2 个进程 · 占 44%');
    expect(memoryRowTitle(v.rows[1]), 'python3 bot.py'); // 去掉路径
    expect(memoryRowLine(v.rows[1]), '程序 · PID 9 · 占 15%');
    expect(memoryRowLine(v.rows[2]), '常驻服务 · 占 不到 1%');
    expect(memoryOtherLine(v), '系统和零碎小程序 · 占 41%');
    expect(memorySemantics(v), contains('大任务，350.0 MB'));

    final t = memoryViewOf(ComputerStatus.fromJson(_status(used: 950 * _mb)))!;
    expect(t.tight, isTrue);
    expect(memoryTightNote(t), allOf(startsWith('快满了'), contains('「大任务」（约 350.0 MB）')));

    // 不出现：休眠、没得排、老服务器没有 memory 字段
    expect(memoryViewOf(ComputerStatus.fromJson(_status(state: 'stopped'))), isNull);
    expect(memoryViewOf(ComputerStatus.fromJson(_status(rows: false))), isNull);
    expect(ComputerStatus.fromJson({'workspace': 'me', 'sandbox': {'state': 'running'}}).memory, isNull);
    // 坏数据：占比夹在 0–1，没上限不画条
    final odd = MemoryView.fromJson({'used': 10, 'rows': [{'kind': '??', 'title': 'x', 'memory': 20, 'share': 2.0}]});
    expect(odd.rows.single.owner, MemoryOwner.process);
    expect(odd.rows.single.share, 1.0);
    expect(odd.ratio, isNull);
    expect(odd.tight, isFalse);
  });

  testWidgets('电脑页：内存一节列出占用者和其它，点后台任务看日志', (tester) async {
    final api = await _pump(tester, _status());
    expect(find.text('内存'), findsOneWidget);
    expect(find.text('已用 800.0 MB，上限 1 GB'), findsOneWidget);
    expect(find.text('大任务'), findsOneWidget);
    expect(find.text('python3 bot.py'), findsOneWidget);
    expect(find.text('其它'), findsOneWidget);
    expect(find.text('328.0 MB'), findsOneWidget);
    expect(find.textContaining('快满了'), findsNothing);

    await tester.tap(find.text('python3 bot.py')); // 程序行不可点：什么也不发生
    await tester.pump();
    await tester.tap(find.text('大任务'));
    for (var i = 0; i < 10; i++) {
      await tester.pump(const Duration(milliseconds: 100));
    }
    expect(api.calls.where((c) => c.contains('/api/jobs/jbig')), isNotEmpty);
  });

  testWidgets('快满了：警示一句点名最大的；休眠时整节不出现', (tester) async {
    await _pump(tester, _status(used: 950 * _mb));
    expect(find.textContaining('最大的是「大任务」'), findsOneWidget);
  });

  testWidgets('休眠：不出现', (tester) async {
    await _pump(tester, _status(state: 'stopped'));
    expect(find.text('内存'), findsNothing);
  });
}
