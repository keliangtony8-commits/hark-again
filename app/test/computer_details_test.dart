// 电脑详情（v1.27）：CPU、内存打满警示、正在运行的程序、磁盘拆分、装过的工具、一键清理。
import 'package:assistant/core/api.dart';
import 'package:assistant/features/computer/computer_details.dart';
import 'package:assistant/features/computer/computer_section.dart';
import 'package:assistant/models/computer.dart';
import 'package:assistant/theme/app_theme.dart';
import 'package:assistant/ui/glass.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

Map<String, dynamic> _status({int oom = 0, int cleanable = 3 << 20, String state = 'running'}) => {
      'workspace': 'me',
      'name': '我的文件',
      'sandbox': {
        'state': state,
        'memory_used': 300 << 20,
        'memory_limit': 1 << 30,
        'cpu_percent': 42.4,
        'oom_kills': oom,
        'processes': [
          {'pid': 42, 'cpu': 87.5, 'memory': 200 << 20, 'elapsed': 185, 'command': '/usr/local/bin/python train.py --epochs 10'},
          {'pid': 43, 'cpu': 3.0, 'memory': 10 << 20, 'elapsed': 20, 'command': 'node'},
        ],
      },
      'disk_used': 0,
      'disk_partial': false,
      'storage': {'files': 10 << 20, 'installed': 50 << 20, 'logs': 1 << 20, 'spill': 0, 'cache': 2 << 20, 'cleanable': cleanable},
      'tools': [
        {'kind': 'npm', 'name': 'pnpm', 'version': '9.1.0'},
        {'kind': 'pip', 'name': 'requests', 'version': '2.32.3'},
        {'kind': 'pip', 'name': 'numpy', 'version': '2.1.0'},
      ],
      'running_jobs': [],
    };

class _Api implements Api {
  _Api(this.status);
  Map<String, dynamic> status;
  final calls = <String>[];
  @override
  Future<dynamic> get(String path) async {
    calls.add('GET $path');
    return status;
  }

  @override
  Future<dynamic> post(String path, [Object? body]) async {
    calls.add('POST $path');
    status = _status(cleanable: 0);
    return {'freed': 3 << 20, 'status': status};
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
      home: const Scaffold(
        body: SingleChildScrollView(
          child: Column(children: [ComputerStatusGroup(ws: 'me'), ProcessSection(ws: 'me'), StorageSection(ws: 'me')]),
        ),
      ),
    ),
  ));
  for (var i = 0; i < 10; i++) {
    await tester.pump(const Duration(milliseconds: 100));
  }
  return api;
}

void main() {
  test('规则：CPU 进说明行、OOM 警示、程序行、磁盘行、清理字样、工具小结', () {
    final s = ComputerStatus.fromJson(_status(oom: 2));
    expect(computerDetail(s), startsWith('CPU 42% · 内存 300.0 MB / 1 GB'));
    expect(computerOomNote(s), contains('强制结束过 2 个程序（上限 1 GB）'));
    expect(computerOomNote(ComputerStatus.fromJson(_status())), isNull);
    expect(computerOomNote(ComputerStatus.fromJson(_status(oom: 2, state: 'stopped'))), isNull); // 关机了计数作废
    expect(processTitle(s.processes.first), 'python train.py --epochs 10');
    expect(processTitle(s.processes.last), 'node');
    expect(processLine(s.processes.first), 'CPU 88% · 内存 200.0 MB · 运行 3 分 05 秒');
    expect([for (final r in storageRows(s.storage)) r.$2], ['文件', '装的软件', '任务日志', '下载缓存']); // 0 字节的存档不列
    expect(cleanupLabel(s.storage), '清理 3.0 MB');
    expect(cleanupLabel(ComputerStatus.fromJson(_status(cleanable: 0)).storage), isNull);
    expect(cleanupDone(0), '没有可清理的了');
    expect(toolsSummary(s.tools), 'pip 2 个 · npm 1 个');
    expect(toolsSummary(const []), startsWith('还没装过'));
    // 老服务器没有这些字段：不炸，默认空
    final old = ComputerStatus.fromJson({'workspace': 'me', 'sandbox': {'state': 'running'}});
    expect(old.processes, isEmpty);
    expect(old.tools, isEmpty);
    expect(old.storage.cleanable, 0);
    expect(old.cpuPercent, isNull);
  });

  testWidgets('详情：警示行、程序列表、磁盘、清理确认后换成新状态', (tester) async {
    final api = await _pump(tester, _status(oom: 1));
    expect(find.textContaining('强制结束过 1 个程序'), findsOneWidget);
    expect(find.text('正在运行的程序'), findsOneWidget);
    expect(find.text('python train.py --epochs 10'), findsOneWidget);
    expect(find.text('装的软件'), findsOneWidget);
    expect(find.text('长输出存档'), findsNothing);
    expect(find.text('pip 2 个 · npm 1 个'), findsOneWidget);

    await tester.tap(find.text('清理 3.0 MB'));
    await tester.pumpAndSettle();
    expect(find.text('清理这台电脑？'), findsOneWidget);
    await tester.tap(find.descendant(of: find.byType(PillButton), matching: find.text('清理')));
    for (var i = 0; i < 10; i++) {
      await tester.pump(const Duration(milliseconds: 100));
    }
    expect(api.calls, contains('POST /api/projects/me/computer/cleanup'));
    expect(find.text('腾出了 3.0 MB'), findsOneWidget);
    await tester.pumpAndSettle();
    expect(find.text('清理 3.0 MB'), findsNothing); // 清完没东西可清：按钮收起
  });

  testWidgets('装过的工具 → 弹层列名字和版本', (tester) async {
    await _pump(tester, _status());
    await tester.tap(find.text('装过的工具'));
    await tester.pumpAndSettle();
    expect(find.text('requests'), findsOneWidget);
    expect(find.text('9.1.0'), findsOneWidget);
  });

  testWidgets('没在跑：不列程序', (tester) async {
    await _pump(tester, _status(state: 'stopped'));
    expect(find.text('正在运行的程序'), findsNothing);
    expect(find.text('磁盘'), findsOneWidget);
  });
}
