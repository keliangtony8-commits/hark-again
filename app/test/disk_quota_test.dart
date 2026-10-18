// 磁盘配额（v1.31）：规则（比例、标题、快满 / 满了的后果）+ 磁盘一节的配额行 + 状态块“磁盘已满”。
import 'package:assistant/core/api.dart';
import 'package:assistant/features/computer/computer_details.dart';
import 'package:assistant/features/computer/computer_section.dart';
import 'package:assistant/models/computer.dart';
import 'package:assistant/theme/app_theme.dart';
import 'package:assistant/ui/kit.dart';
import 'package:assistant/ui/motion.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

Map<String, dynamic> _status({int used = 1 << 30, int? limit = 3 << 30, String level = 'ok'}) => {
      'workspace': 'me',
      'name': '我的文件',
      'sandbox': {'state': 'stopped', 'idle_minutes': 15},
      'disk_used': used,
      'disk_partial': false,
      'disk_limit': limit,
      'disk_level': level,
      'storage': {'files': used, 'installed': 0, 'logs': 0, 'spill': 0, 'cache': 0, 'cleanable': 0},
      'tools': [],
      'running_jobs': [],
    };

class _Api implements Api {
  _Api(this.status);
  Map<String, dynamic> status;
  @override
  Future<dynamic> get(String path) async => status;
  @override
  dynamic noSuchMethod(Invocation i) => throw UnimplementedError();
}

Future<void> _pump(WidgetTester tester, Map<String, dynamic> status) async {
  tester.view.physicalSize = const Size(400, 1200);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(ProviderScope(
    overrides: [apiProvider.overrideWithValue(_Api(status))],
    child: MaterialApp(
      theme: buildTheme(Brightness.light),
      home: const Scaffold(
        body: SingleChildScrollView(child: Column(children: [ComputerStatusGroup(ws: 'me'), StorageSection(ws: 'me')])),
      ),
    ),
  ));
  for (var i = 0; i < 10; i++) {
    await tester.pump(const Duration(milliseconds: 100));
  }
}

void main() {
  test('rules', () {
    final ok = ComputerStatus.fromJson(_status());
    expect(ok.diskLimit, 3 << 30);
    expect(ok.diskTight, isFalse);
    expect(computerDiskRatio(ok), closeTo(1 / 3, 1e-9));
    expect(computerDiskLine(ok), '已用 1 GB，上限 3 GB');
    expect(computerDiskNote(ok), isNull);
    expect(computerDetail(ok), contains('文件 1 GB / 3 GB'));
    expect(computerHint(ok), isNull);

    final tight = ComputerStatus.fromJson(_status(used: (2.7 * (1 << 30)).round(), level: 'tight'));
    expect(tight.diskTight, isTrue);
    expect(tight.diskFull, isFalse);
    expect(computerDiskNote(tight), startsWith('空间紧张'));

    final full = ComputerStatus.fromJson(_status(used: 4 << 30, level: 'full'));
    expect(computerDiskRatio(full), 1.0);
    expect(computerDiskNote(full), contains('无法写入新文件'));
    expect(computerHint(full), '磁盘已满');

    final off = ComputerStatus.fromJson(_status(limit: null, level: 'off'));
    expect(computerDiskRatio(off), isNull);
    expect(computerDetail(off), isNot(contains(' / ')));
    // 老服务器没这两个字段：当作不限
    final old = ComputerStatus.fromJson(_status()..remove('disk_limit')..remove('disk_level'));
    expect(old.diskLimit, isNull);
    expect(old.diskLevel, 'off');
  });

  testWidgets('quota row shows usage; full warns in both sections', (tester) async {
    await _pump(tester, _status(used: 4 << 30, level: 'full'));
    expect(find.text('已用 4 GB，上限 3 GB'), findsOneWidget);
    expect(find.textContaining('已满：无法写入新文件'), findsOneWidget);
    expect(find.byType(MeterBar), findsOneWidget);
    final hint = tester.widget<RowHint>(find.widgetWithText(RowHint, '磁盘已满'));
    expect(hint.warn, isTrue);
  });

  testWidgets('no limit → no quota row', (tester) async {
    await _pump(tester, _status(limit: null, level: 'off'));
    expect(find.textContaining('上限'), findsNothing);
    expect(find.byType(MeterBar), findsNothing);
  });
}
