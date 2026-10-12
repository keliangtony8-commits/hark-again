// v1.92 后台任务内存（后端 app/job_memory.py）：上限 / 峰值 / 整台沙盒快满了的解析和文案，
// 任务卡上“内存 x / 上限”快到上限变警示色、整台快满了的提醒行、失败原因（内存超限）写在日志下面、结束后峰值进底栏。
import 'package:assistant/blocks/job_block.dart';
import 'package:assistant/core/api.dart';
import 'package:assistant/core/cache.dart';
import 'package:assistant/models/block.dart';
import 'package:assistant/models/job.dart';
import 'package:assistant/theme/app_theme.dart';
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

const _mb = 1024 * 1024;
const _use = {'cpu': 20.0, 'cpu_seconds': 5.0, 'memory': 90 * _mb, 'processes': 1};
const _box = {'used': 3900 * _mb, 'limit': 4096 * _mb};
const _reason = '内存超过给它定的上限 100 MB（当时约 130 MB），已强制结束';

Map<String, dynamic> _wire(String state, {Object? usage, Object? box, int? max, int? peak, String? reason}) => {
      'id': 'j1', 'title': '处理数据', 'command': 'python etl.py', 'state': state, 'followup': 'none', 'elapsed': 5,
      'tail': 'row 1', 'usage': usage, 'box': box, 'memory_max': max, 'memory_peak': peak, 'stop_reason': reason,
    };

void main() {
  test('解析：上限 / 峰值 / 整台', () {
    final j = JobInfo.fromJson(_wire('running', usage: _use, box: _box, max: 100 * _mb));
    expect(j.memoryMax, 100 * _mb);
    expect(j.box!.percent, 95);
    expect(j.memoryNear, isTrue); // 90 / 100 ≥ 0.8
    expect(j.boxTight, isTrue);
    expect(JobInfo.fromJson(_wire('running', usage: _use, max: 200 * _mb)).memoryNear, isFalse);
    expect(JobInfo.fromJson(_wire('running', usage: _use)).memoryNear, isFalse); // 没设上限
    expect(JobInfo.fromJson(_wire('running', box: {'used': 1, 'limit': 100})).boxTight, isFalse);
    expect(JobInfo.fromJson(_wire('done', box: _box)).boxTight, isFalse); // 结束了不提醒
    for (final bad in [null, 'x', {'used': -1, 'limit': 9}, {'used': 1, 'limit': 0}, {'used': '1', 'limit': 9}]) {
      expect(JobBox.tryParse(bad), isNull, reason: '$bad');
    }
    expect(JobBox.tryParse({'used': 50, 'limit': 10})!.used, 10);
    expect(JobInfo.fromJson(_wire('running', max: 0)).memoryMax, isNull);
    final b = JobBlock.fromJson({'id': 'j1', 'title': 't', 'command': 'c', 'state': 'failed', 'memory_max': 100 * _mb, 'memory_peak': 130 * _mb});
    final fromBlock = JobInfo.fromBlock(b);
    expect([fromBlock.memoryMax, fromBlock.memoryPeak], [100 * _mb, 130 * _mb]);
    expect(fromBlock.withElapsed(Duration.zero).memoryPeak, 130 * _mb);
  });

  test('文案', () {
    final u = JobUsage.tryParse(_use)!;
    expect(jobMemoryLabel(u, max: 100 * _mb), '内存 90.0 MB / 100.0 MB');
    expect(jobBoxLabel(JobBox.tryParse(_box)!), '这台电脑内存已用 95%（3.8 GB / 4 GB），再涨系统会强制结束进程');
    final failed = JobInfo.fromJson(_wire('failed', peak: 130 * _mb, reason: _reason, max: 100 * _mb));
    expect(failed.showsReason, isTrue);
    expect(failed.autoStopped, isFalse);
    expect(jobFootLabel(failed), '失败 · 内存峰值 130.0 MB');
    expect(jobSemantics(failed), contains(_reason));
    final running = JobInfo.fromJson(_wire('running', usage: _use, box: _box, max: 100 * _mb, peak: 90 * _mb));
    expect(jobFootLabel(running), '运行中'); // 在跑时峰值不进底栏
    expect(jobSemantics(running), allOf(contains('内存上限 100.0 MB'), contains('这台电脑内存已用 95%')));
  });

  testWidgets('任务卡：快到上限变警示色、整台快满了提醒，被结束后原因在日志下面、峰值在底栏', (tester) async {
    final api = _Api([
      _wire('running', usage: _use, box: _box, max: 100 * _mb),
      _wire('failed', max: 100 * _mb, peak: 130 * _mb, reason: _reason),
    ]);
    tester.view.physicalSize = const Size(400, 900);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    await tester.pumpWidget(ProviderScope(
      overrides: [apiProvider.overrideWithValue(api), cacheStoreProvider.overrideWithValue(MemoryCacheStore())],
      child: MaterialApp(
        theme: buildTheme(Brightness.light),
        home: const Scaffold(
            body: JobBlockView(JobBlock(id: 'j1', title: '处理数据', command: 'python etl.py', state: 'running', memoryMax: 100 * _mb))),
      ),
    ));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 600));
    final mem = find.text('内存 90.0 MB / 100.0 MB');
    expect(mem, findsOneWidget);
    final ctx = tester.element(mem);
    expect(tester.widget<Text>(mem).style?.color, ctx.palette.warning);
    expect(find.textContaining('这台电脑内存已用 95%'), findsOneWidget);
    expect(tester.takeException(), isNull);
    await tester.pump(const Duration(seconds: 2)); // 下一次轮询：被结束了
    await tester.pump(const Duration(seconds: 1));
    expect(find.textContaining('这台电脑内存已用'), findsNothing);
    expect(find.text(_reason), findsOneWidget);
    expect(find.text('失败 · 内存峰值 130.0 MB'), findsOneWidget);
  });
}
