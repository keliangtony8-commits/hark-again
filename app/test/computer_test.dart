// 工作区的“电脑”（v1.25）：models/computer.dart 的文案规则 + ComputerSection（状态、内存条、正在跑的任务、取消、重启确认）。
import 'package:assistant/core/api.dart';
import 'package:assistant/features/computer/computer_section.dart';
import 'package:assistant/models/computer.dart';
import 'package:assistant/theme/app_theme.dart';
import 'package:assistant/ui/format.dart';
import 'package:assistant/ui/glass.dart';
import 'package:assistant/ui/motion.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

Map<String, dynamic> _status({String state = 'running', bool job = true, int used = 300 << 20, List<Map<String, dynamic>> services = const []}) => {
      'services': services,
      'workspace': 'me',
      'name': '我的文件',
      'sandbox': state == 'unreachable'
          ? {'state': 'unreachable'}
          : {'state': state, 'memory_used': state == 'running' ? used : null, 'memory_limit': state == 'running' ? 1 << 30 : null,
              'started_at': '2026-10-12T05:01:02+00:00', 'idle_minutes': 30, 'outdated': false},
      'disk_used': 120 << 20,
      'disk_partial': false,
      'running_jobs': [
        if (job)
          {'id': 'j1', 'title': '训练模型', 'command': 'python train.py\nmore', 'state': 'running', 'elapsed': 185, 'tail': 'epoch 3'},
      ],
    };

Map<String, dynamic> _svc(String health, {int restarts = 0, List<int> ports = const [8000], String? reason, String? at}) => {
      'id': 's1', 'title': '机器人', 'command': 'python bot.py', 'keep_alive': true, 'restarts': restarts,
      'state': health == 'gave_up' ? 'failed' : 'running', 'exit_code': health == 'up' ? null : 1, 'elapsed': 4000,
      'health': health, 'ports': health == 'up' ? ports : <int>[], 'uptime': health == 'up' ? 3720 : null,
      'stop_reason': reason, 'restart_at': at,
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
    if (path.startsWith('/api/jobs/') && path.endsWith('/restart')) {
      status = _status(job: false, services: [_svc('up', restarts: 1)]);
      return {'id': 's1', 'state': 'running'};
    }
    status = _status(job: false);
    return path.endsWith('/restart') ? status : {'id': 'j1', 'state': 'cancelled'};
  }

  @override
  dynamic noSuchMethod(Invocation i) => throw UnimplementedError();
}

Future<_Api> _pump(WidgetTester tester, Map<String, dynamic> status) async {
  tester.view.physicalSize = const Size(400, 800);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  final api = _Api(status);
  await tester.pumpWidget(ProviderScope(
    overrides: [apiProvider.overrideWithValue(api)],
    child: MaterialApp(
      theme: buildTheme(Brightness.light),
      home: const Scaffold(body: SingleChildScrollView(child: ComputerSection(ws: 'me'))),
    ),
  ));
  for (var i = 0; i < 10; i++) {
    await tester.pump(const Duration(milliseconds: 100));
  }
  return api;
}

void main() {
  test('规则：状态词、说明行、内存比例、行尾小字、重启说明', () {
    final run = ComputerStatus.fromJson(_status());
    expect(computerStateLabel(run.state), '运行中');
    expect(computerDetail(run), '内存 300.0 MB / 1 GB · 文件 120.0 MB');
    expect(computerMemoryRatio(run), closeTo(300 / 1024, 1e-9));
    expect(computerHint(run), '1 个任务在跑');
    expect(computerRestartText(run), startsWith('会停掉 1 个正在跑的后台任务。'));
    expect(run.jobs.single.elapsed, const Duration(seconds: 185));

    final idle = ComputerStatus.fromJson(_status(job: false));
    expect(computerHint(idle), '空闲');
    expect(computerRestartText(idle), '文件和装过的软件都在，下次用到时自动开机。');

    final sleep = ComputerStatus.fromJson(_status(state: 'stopped', job: false));
    expect(computerStateLabel(sleep.state), '休眠中');
    expect(computerDetail(sleep), '空闲 30 分钟自动休眠，用到时自动开机 · 文件 120.0 MB');
    expect(computerMemoryRatio(sleep), isNull);
    expect(computerHint(sleep), isNull);

    // v1.74 休眠原因：给其它工作区腾内存 / 空闲；不认识的原因当没说
    Map<String, dynamic> slept(Object? by) {
      final j = _status(state: 'stopped', job: false);
      (j['sandbox'] as Map)['stopped_by'] = by;
      return j;
    }
    final room = ComputerStatus.fromJson(slept('room'));
    expect(room.stoppedBy, ComputerStopReason.room);
    expect(computerDetail(room), '给正在用的其它工作区腾内存，先休眠了，用到时自动开机 · 文件 120.0 MB');
    expect(ComputerStatus.fromJson(slept('idle')).stoppedBy, ComputerStopReason.idle);
    expect(computerDetail(ComputerStatus.fromJson(slept('idle'))), '空闲 30 分钟自动休眠，用到时自动开机 · 文件 120.0 MB');
    expect(ComputerStatus.fromJson(slept('weird')).stoppedBy, isNull);

    final none = ComputerStatus.fromJson(_status(state: 'none', job: false));
    expect(computerDetail(none), startsWith('第一次跑命令时开机'));

    final down = ComputerStatus.fromJson(_status(state: 'unreachable', job: false));
    expect(down.reachable, isFalse);
    expect(computerStateLabel(down.state), '连不上沙盒');
    expect(computerSemantics(down), contains('沙盒服务没在跑'));

    expect(formatSize(3 << 30), '3 GB');
    expect(formatSize((1.5 * (1 << 30)).round()), '1.5 GB');
  });

  testWidgets('运行中：状态 + 内存条 + 任务行；取消走 /api/jobs/{id}/cancel 后刷新', (tester) async {
    final api = await _pump(tester, _status());
    expect(api.calls.first, 'GET /api/projects/me/computer');
    expect(find.text('运行中'), findsOneWidget);
    expect(find.text('1 个任务在跑'), findsOneWidget);
    expect(find.byType(MeterBar), findsOneWidget);
    expect(find.text('训练模型'), findsOneWidget);
    expect(find.text('运行 3 分 05 秒 · \$ python train.py'), findsOneWidget);
    await tester.tap(find.text('取消'));
    for (var i = 0; i < 10; i++) {
      await tester.pump(const Duration(milliseconds: 100));
    }
    expect(api.calls, containsAllInOrder(['POST /api/jobs/j1/cancel', 'GET /api/projects/me/computer']));
    expect(find.text('训练模型'), findsNothing);
    expect(find.text('空闲'), findsOneWidget);
  });

  test('v1.82 常驻服务：健康、副标题、按钮字、行尾小字、重启说明', () {
    final up = ServiceInfo.fromJson(_svc('up', restarts: 2, ports: [8000, 3000]));
    expect(up.health, ServiceHealth.up);
    expect(serviceLine(up), '运行 1 小时 02 分 · 端口 8000、3000 · 已重启 2 次');
    expect(serviceAction(up.health), '重启');
    final now = DateTime.now();
    final wait = ServiceInfo.fromJson(_svc('restarting', at: now.add(const Duration(seconds: 40)).toUtc().toIso8601String()));
    expect(serviceLine(wait, now: now), anyOf('40 秒后重启 · 上次退出码 1', '39 秒后重启 · 上次退出码 1'));
    expect(serviceAction(wait.health), '立即重启');
    expect(serviceLine(ServiceInfo.fromJson(_svc('restarting')), now: now), '马上重启 · 上次退出码 1');
    final dead = ServiceInfo.fromJson(_svc('gave_up', reason: '连续 6 次启动后不到 1 分钟就退出，已停止自动重启'));
    expect(serviceLine(dead), '连续 6 次启动后不到 1 分钟就退出，已停止自动重启');
    expect(serviceLine(ServiceInfo.fromJson(_svc('gave_up'))), '意外退出（退出码 1）');
    expect(serviceAction(dead.health), '重新启动');
    expect(serviceSemantics(dead), startsWith('常驻服务 机器人，已停止，'));

    final s = ComputerStatus.fromJson(_status(job: false, services: [_svc('up')]));
    expect(s.liveServices, 1);
    expect(s.busy, isTrue);
    expect(computerHint(s), '1 个服务在跑');
    expect(computerHintWarn(s), isFalse);
    expect(computerRestartText(s), '1 个常驻服务会马上重新拉起。文件和装过的软件都在，下次用到时自动开机。');
    final bad = ComputerStatus.fromJson(_status(services: [_svc('gave_up')]));
    expect(computerHint(bad), '1 个服务停了');
    expect(computerHintWarn(bad), isTrue);
    expect(bad.busy, isTrue); // 普通任务在跑
    expect(ComputerStatus.fromJson(_status(job: false, services: [_svc('gave_up')])).busy, isFalse);
    expect(computerSemantics(bad), endsWith('1 个服务停了'));
  });

  testWidgets('常驻服务：停了的行警示 + 重新启动 → POST /api/jobs/{id}/restart 后刷新成在跑', (tester) async {
    final api = await _pump(tester, _status(job: false, services: [_svc('gave_up', reason: '已停止自动重启')]));
    expect(find.text('机器人'), findsOneWidget);
    expect(find.text('1 个服务停了'), findsOneWidget);
    expect(find.textContaining('已停止自动重启'), findsOneWidget);
    await tester.tap(find.text('重新启动'));
    for (var i = 0; i < 10; i++) {
      await tester.pump(const Duration(milliseconds: 100));
    }
    expect(api.calls, containsAllInOrder(['POST /api/jobs/s1/restart', 'GET /api/projects/me/computer']));
    expect(find.text('运行 1 小时 02 分 · 端口 8000 · 已重启 1 次'), findsOneWidget);
    expect(find.text('1 个服务在跑'), findsOneWidget);
    expect(find.text('重新启动'), findsNothing);
    await tester.pump(const Duration(seconds: 4)); // 吐司走完
  });

  testWidgets('重启：先确认，确认后 POST restart', (tester) async {
    final api = await _pump(tester, _status());
    await tester.tap(find.text('重启'));
    for (var i = 0; i < 10; i++) {
      await tester.pump(const Duration(milliseconds: 100));
    }
    expect(find.text('重启这台电脑？'), findsOneWidget);
    expect(find.textContaining('会停掉 1 个'), findsOneWidget);
    await tester.tap(find.descendant(of: find.byType(PillButton), matching: find.text('重启')));
    for (var i = 0; i < 10; i++) {
      await tester.pump(const Duration(milliseconds: 100));
    }
    expect(api.calls, contains('POST /api/projects/me/computer/restart'));
    expect(find.text('训练模型'), findsNothing);
  });

  testWidgets('休眠 / 连不上：没有重启钮、没有内存条；连不上用警示图标', (tester) async {
    await _pump(tester, _status(state: 'stopped', job: false));
    expect(find.text('休眠中'), findsOneWidget);
    expect(find.text('重启'), findsNothing);
    expect(find.byType(MeterBar), findsNothing);
  });

  testWidgets('连不上沙盒', (tester) async {
    await _pump(tester, _status(state: 'unreachable', job: false));
    expect(find.text('连不上沙盒'), findsOneWidget);
    expect(find.byIcon(Icons.cloud_off_rounded), findsOneWidget);
    expect(find.text('重启'), findsNothing);
  });

  test('v2.85 同名服务合并（earlier_stops）+ 整台服务器一行 + 页头说清是隔出来的一块', () {
    final merged = ServiceInfo.fromJson({..._svc('up'), 'earlier_stops': 2});
    expect(merged.earlierStops, 2);
    expect(serviceLine(merged), '运行 1 小时 02 分 · 端口 8000 · 24 小时内停过 2 次');
    expect(ServiceInfo.fromJson(_svc('up')).earlierStops, 0);

    expect(ComputerStatus.fromJson(_status()).machine, isNull); // 项目的电脑不给
    final m = ComputerStatus.fromJson({..._status(), 'machine': {'cpus': 2, 'load1': 0.34, 'memory_total': 4 << 30,
        'memory_used': 1 << 30, 'disk_total': 40 << 30, 'disk_used': 12 << 30}}).machine!;
    expect(machineLine(m), '2 核（负载 0.3） · 内存 ${formatSize(1 << 30)} / ${formatSize(4 << 30)} · 磁盘 ${formatSize(12 << 30)} / ${formatSize(40 << 30)}');
    expect(machineLine(const MachineInfo()), isNull);
    expect(machineLine(const MachineInfo(memoryTotal: 4 << 30)), '内存 ${formatSize(4 << 30)}');

    final s = ComputerStatus.fromJson({..._status(), 'disk_limit': 3 << 30});
    expect(computerIntro(s, personal: true),
        startsWith('你的云电脑是服务器上隔出来的一块云端 Linux（内存 ${formatSize(1 << 30)} · 空间 ${formatSize(3 << 30)}）：'));
    expect(computerIntro(null, personal: false), startsWith('这个项目的云电脑是服务器上隔出来的一块云端 Linux：'));
  });

  testWidgets('v2.85 个人电脑多一行“整台服务器”，没有 machine 就不画', (tester) async {
    await _pump(tester, {..._status(job: false), 'machine': {'cpus': 4, 'memory_total': 4 << 30, 'memory_used': 1 << 30}});
    expect(find.text('整台服务器'), findsOneWidget);
    expect(find.textContaining('4 核'), findsOneWidget);
  });
}
