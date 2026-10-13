// v1.98 “我的电脑”页“最近 7 天谁写得最多”（服务器 app/job_disk.leaders → computer 状态的 disk_jobs）。
import 'package:assistant/core/api.dart';
import 'package:assistant/features/computer/computer_details.dart';
import 'package:assistant/models/computer.dart';
import 'package:assistant/theme/app_theme.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

const mb = 1 << 20;
final now = DateTime.utc(2026, 10, 13, 8);

Map<String, dynamic> _job(String id, String title, Map<String, dynamic>? disk, {bool kept = true, int daysAgo = 2}) => {
      'id': id,
      'title': title,
      'command': 'npm install',
      'state': 'done',
      'elapsed': 30,
      'finished_at': now.subtract(Duration(days: daysAgo)).toIso8601String(),
      'disk': disk,
      'log_kept': kept,
    };

Map<String, dynamic> _disk(int written, int log, {String? top, int overlap = 0, bool partial = false}) => {
      'log': log,
      'written': written,
      'files': written > 0 ? 3 : 0,
      'overlap': overlap,
      'partial': partial,
      'top': [if (top != null) {'path': top, 'size': written}],
    };

Map<String, dynamic> _status(List<Map<String, dynamic>> jobs, {int used = 1000 * mb}) => {
      'workspace': 'me',
      'sandbox': {'state': 'stopped'},
      'disk_used': used,
      'storage': {'files': used, 'cleanable': 0},
      'running_jobs': [],
      'disk_jobs': jobs,
    };

class _Api implements Api {
  _Api(this.status);
  final Map<String, dynamic> status;
  final calls = <String>[];
  @override
  Future<dynamic> get(String path) async {
    calls.add(path);
    return path.startsWith('/api/jobs/') ? {'id': 'j1', 'tail': '装好了', 'disk': status['disk_jobs'][0]['disk']} : status;
  }

  @override
  dynamic noSuchMethod(Invocation i) => throw UnimplementedError();
}

void main() {
  test('规则：解析、去掉没账的、日志清了不算日志、排序、占比、说明、读屏', () {
    final s = ComputerStatus.fromJson(_status([
      _job('j1', '装依赖', _disk(300 * mb, 2 * mb, top: 'node_modules/', overlap: 1)),
      _job('j2', '爬图片', _disk(40 * mb, 60 * mb, top: 'images/', partial: true), kept: false, daysAgo: 3),
      _job('j3', '只有日志', _disk(0, 5 * mb)),
      _job('j4', '日志清了', _disk(0, 5 * mb), kept: false),
      _job('j5', '老任务', null),
      _job('j6', '坏账', {'log': -1, 'written': 0, 'files': 0}),
      _job('j7', '空账', _disk(0, 0)),
    ]));
    expect([for (final r in s.diskJobs) r.job.id], ['j1', 'j2', 'j3', 'j4']); // 没账 / 坏账 / 零账不进
    final rows = diskJobRows(s);
    expect([for (final r in rows) r.job.id], ['j1', 'j2', 'j3']); // 日志清了又没写文件 → 不列
    expect(rows[0].total, 302 * mb);
    expect(rows[1].total, 40 * mb); // 日志清了只剩写的文件
    expect(diskJobSize(rows[0]), '302.0 MB');
    expect(diskJobSize(rows[1]), '40.0 MB+');
    expect(diskJobLine(rows[0], now: now), '2 天前 · 主要写在 node_modules/ · 日志 2.0 MB · 含同时段任务');
    expect(diskJobLine(rows[1], now: now), '3 天前 · 主要写在 images/ · 日志已清');
    expect(diskJobLine(rows[2], now: now), '2 天前 · 只有日志 · 日志 5.0 MB');
    expect(diskJobShare(s, rows[0]), closeTo(0.302, 0.001));
    expect(diskJobsNote(s), contains('日志共 7.0 MB 可以清'));
    expect(diskJobsSemantics(s, now: now), startsWith('最近 7 天谁写得最多；装依赖，302.0 MB'));
    // 已用不知道 → 按最大那行算
    final z = ComputerStatus.fromJson(_status([_job('j1', 'a', _disk(10 * mb, 0, top: 'x/'))], used: 0));
    expect(diskJobShare(z, diskJobRows(z).first), 1.0);
    // 装的软件改名
    final h = ComputerStatus.fromJson(_status([_job('j1', 'pip', _disk(10 * mb, 0, top: '.home/'))]));
    expect(diskJobLine(diskJobRows(h).first, now: now), contains('主要写在 装的软件'));
    expect(diskJobsNote(h), isNot(contains('可以清')));
    // 老服务器没这个字段
    expect(ComputerStatus.fromJson({'workspace': 'me', 'sandbox': {'state': 'none'}}).diskJobs, isEmpty);
  });

  Future<_Api> pump(WidgetTester tester, Map<String, dynamic> status) async {
    tester.view.physicalSize = const Size(400, 1200);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    final api = _Api(status);
    await tester.pumpWidget(ProviderScope(
      overrides: [apiProvider.overrideWithValue(api)],
      child: MaterialApp(
        theme: buildTheme(Brightness.light),
        home: const Scaffold(body: SingleChildScrollView(child: DiskJobsSection(ws: 'me'))),
      ),
    ));
    for (var i = 0; i < 10; i++) {
      await tester.pump(const Duration(milliseconds: 100));
    }
    return api;
  }

  testWidgets('有账：标题、行、点开看日志和磁盘明细', (tester) async {
    final api = await pump(tester, _status([
      _job('j1', '装依赖', _disk(300 * mb, 2 * mb, top: 'node_modules/')),
      _job('j2', '爬图片', _disk(40 * mb, 0, top: 'images/')),
    ]));
    expect(find.text(diskJobsTitle), findsOneWidget);
    expect(find.text('装依赖'), findsOneWidget);
    expect(find.text('302.0 MB'), findsOneWidget);
    expect(find.textContaining('主要写在 node_modules/'), findsOneWidget);
    await tester.tap(find.text('装依赖'));
    await tester.pumpAndSettle();
    expect(api.calls.any((c) => c.startsWith('/api/jobs/j1')), isTrue);
    expect(find.textContaining('运行期间新写或改过'), findsOneWidget);
  });

  testWidgets('没账：整节不出现', (tester) async {
    await pump(tester, _status([_job('j5', '老任务', null)]));
    expect(find.text(diskJobsTitle), findsNothing);
  });
}
