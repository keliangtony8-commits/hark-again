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

Map<String, dynamic> _status({String state = 'running', bool job = true, int used = 300 << 20}) => {
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
}
