// v1.90 每个后台任务占多少 CPU / 内存（后端 app/job_usage.py）：解析宁缺毋错、文案、任务卡上的占用条
// （在跑且问得到才出现，结束后收起）、“这台电脑”里任务行 / 常驻服务行的副标题。
import 'package:assistant/blocks/job_block.dart';
import 'package:assistant/core/api.dart';
import 'package:assistant/core/cache.dart';
import 'package:assistant/models/block.dart';
import 'package:assistant/models/computer.dart';
import 'package:assistant/models/job.dart';
import 'package:assistant/theme/app_theme.dart';
import 'package:assistant/ui/motion.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

class _Api implements Api {
  _Api(this.replies);
  final List<Map<String, dynamic>> replies;

  @override
  Future<dynamic> get(String path) async => replies.length > 1 ? replies.removeAt(0) : replies.first;

  @override
  dynamic noSuchMethod(Invocation i) => throw UnimplementedError();
}

const _use = {'cpu': 93.4, 'cpu_seconds': 125.0, 'memory': 125829120, 'processes': 3};

Map<String, dynamic> _wire(String state, {Object? usage, bool keepAlive = false}) => {
      'id': 'j1', 'title': '训练模型', 'command': 'python train.py', 'state': state, 'followup': 'none', 'elapsed': 5,
      'tail': 'epoch 1', 'keep_alive': keepAlive, 'usage': usage,
    };

void main() {
  test('解析：缺字段 / 负数 / 0 个进程 → 没有', () {
    final u = JobUsage.tryParse(_use)!;
    expect(u.cpu, 93.4);
    expect(u.processes, 3);
    expect(JobUsage.tryParse(null), isNull);
    expect(JobUsage.tryParse('x'), isNull);
    expect(JobUsage.tryParse({..._use, 'cpu': '9'}), isNull);
    expect(JobUsage.tryParse({..._use, 'memory': -1}), isNull);
    expect(JobUsage.tryParse({..._use, 'processes': 0}), isNull);
    expect(JobUsage.tryParse({'cpu': 1}), isNull);
    expect(JobInfo.fromJson(_wire('running', usage: _use)).usage, u);
    expect(JobInfo.fromJson(_wire('running')).usage, isNull);
    expect(JobInfo.fromJson(_wire('running', usage: _use)).withElapsed(const Duration(seconds: 9)).usage, u);
  });

  test('文案', () {
    expect(jobCpuLabel(0), '0%');
    expect(jobCpuLabel(0.44), '0.4%');
    expect(jobCpuLabel(35.6), '36%');
    final u = JobUsage.tryParse(_use)!;
    expect(jobUsageLabel(u), 'CPU 93% · 内存 120.0 MB · 3 个进程');
    expect(jobMemoryLabel(u), '内存 120.0 MB · 3 个进程');
    final one = JobUsage.tryParse({..._use, 'processes': 1, 'cpu': 2.5})!;
    expect(jobUsageLabel(one), 'CPU 2.5% · 内存 120.0 MB');
    expect(jobUsageSemantics(u), '占用 CPU 93%，内存 120.0 MB，3 个进程');
    final j = JobInfo.fromJson(_wire('running', usage: _use));
    expect(jobRowSubtitle(j), '运行 5 秒 · CPU 93% · 内存 120.0 MB · 3 个进程 · \$ python train.py');
    expect(jobRowSubtitle(JobInfo.fromJson(_wire('running'))), '运行 5 秒 · \$ python train.py');
    expect(jobSemantics(j), contains('占用 CPU 93%'));
    expect(jobSemantics(JobInfo.fromJson(_wire('done', usage: _use))), isNot(contains('占用')));
    final svc = ServiceInfo.fromJson({..._wire('running', usage: _use, keepAlive: true), 'health': 'up', 'uptime': 60, 'ports': [8000]});
    expect(serviceLine(svc), '运行 1 分 00 秒 · 端口 8000 · CPU 93% · 内存 120.0 MB · 3 个进程');
  });

  testWidgets('任务卡：问到占用才出现 CPU 条，吃满变警示色，结束后收起', (tester) async {
    final api = _Api([_wire('running'), _wire('running', usage: _use), _wire('done', usage: _use)]);
    tester.view.physicalSize = const Size(400, 800);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    await tester.pumpWidget(ProviderScope(
      overrides: [apiProvider.overrideWithValue(api), cacheStoreProvider.overrideWithValue(MemoryCacheStore())],
      child: MaterialApp(
        theme: buildTheme(Brightness.light),
        home: const Scaffold(body: JobBlockView(JobBlock(id: 'j1', title: '训练模型', command: 'python train.py', state: 'running'))),
      ),
    ));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 600));
    expect(find.byType(MeterBar), findsNothing); // 第一次没有占用：不画成 0
    await tester.pump(const Duration(seconds: 2)); // 下一次轮询
    await tester.pump(const Duration(milliseconds: 600));
    expect(find.text('CPU 93%'), findsOneWidget);
    expect(find.text('内存 120.0 MB · 3 个进程'), findsOneWidget);
    final bar = tester.widget<MeterBar>(find.byType(MeterBar));
    expect(bar.value, closeTo(0.934, 1e-9));
    final ctx = tester.element(find.byType(MeterBar));
    expect(bar.color, ctx.palette.warning);
    await tester.pump(const Duration(seconds: 2)); // 结束了：收起
    await tester.pump(const Duration(seconds: 1));
    expect(find.byType(MeterBar), findsNothing);
    expect(find.text('已完成'), findsOneWidget);
  });
}
