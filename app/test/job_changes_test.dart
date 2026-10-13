// v2.18 后台任务改了哪些文件：任务卡里嵌的改动区（ChangesPanel scope = job）——解析、措辞、撤销走 /api/jobs/{id}/changes/undo。
import 'package:assistant/blocks/job_block.dart';
import 'package:assistant/core/api.dart';
import 'package:assistant/core/cache.dart';
import 'package:assistant/models/block.dart';
import 'package:assistant/models/changes.dart';
import 'package:assistant/models/job.dart';
import 'package:assistant/theme/app_theme.dart';
import 'package:assistant/ui/glass.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

Map<String, dynamic> _changes({bool undone = false, bool overlap = true, int shared = 1}) => {
      'type': 'changes', 'token': 'tok1', 'undone': undone, 'overlap': overlap, 'shared': shared,
      'files': [
        {'path': 'out/result.csv', 'added': 3, 'removed': 0, 'diff': '+a\n+b\n+c', 'created': true},
        {'path': 'run.sh', 'added': 0, 'removed': 0, 'diff': '', 'mode': '加了可执行'},
      ],
    };

Map<String, dynamic> _wire({bool undone = false}) => {
      'id': 'j1', 'title': '处理数据', 'command': 'python job.py', 'state': 'done', 'exit_code': 0,
      'followup': 'done', 'elapsed': 30, 'tail': 'ok', 'changes': _changes(undone: undone),
    };

class _Api implements Api {
  _Api(this.reply);
  final Object Function() reply;
  final posts = <String>[];
  @override
  Future<dynamic> post(String path, [Object? body]) async {
    posts.add(path);
    final r = reply();
    if (r is ApiError) throw r;
    return r;
  }

  @override
  Future<dynamic> get(String path) async => _wire();

  @override
  dynamic noSuchMethod(Invocation i) => throw UnimplementedError();
}

Future<void> _pump(WidgetTester t, _Api api, JobBlock block) async {
  t.view.physicalSize = const Size(420, 1000);
  t.view.devicePixelRatio = 1;
  addTearDown(t.view.reset);
  await t.pumpWidget(ProviderScope(
    overrides: [apiProvider.overrideWithValue(api), cacheStoreProvider.overrideWithValue(MemoryCacheStore())],
    child: MaterialApp(
      theme: buildTheme(Brightness.light),
      home: Scaffold(body: Padding(padding: const EdgeInsets.all(16), child: SingleChildScrollView(child: JobBlockView(block)))),
    ),
  ));
  await t.pumpAndSettle();
}

void main() {
  test('解析 + 措辞', () {
    final b = JobBlock.fromJson(_wire());
    final c = b.changes!;
    expect(c.overlap, isTrue);
    expect(c.shared, 1);
    expect(jobChangesShown(c), isTrue);
    expect(jobChangesShown(null), isFalse);
    expect(jobChangesShown(const ChangesBlock()), isFalse);
    expect(changesTitle(c, scope: ChangesScope.job), '任务改了 2 个文件');
    expect(changesTitle(c), '改了 2 个文件');
    expect(changesNote(c, scope: ChangesScope.job), '同时还有别的后台任务，可能也算进来了 · 另有 1 个文件这期间对话里也改过，算在那一轮');
    expect(changesConfirm(c, scope: ChangesScope.job).$1, '撤销这个任务的文件改动？');
    final u = ChangesBlock.fromJson(_changes(undone: true));
    expect(changesNote(u, scope: ChangesScope.job), '文件已回到任务开始前的样子');
    expect(changesNote(u), '文件已回到这一轮之前的样子');
    expect(ChangesBlock.tryParse('junk'), isNull);
    expect(JobBlock.fromJson({'id': 'x', 'title': 't', 'command': 'c', 'state': 'done'}).changes, isNull);
    final info = JobInfo.fromJson(_wire());
    expect(info.changes!.files.length, 2);
    expect(jobSemantics(info), contains('任务改了 2 个文件'));
    expect(JobInfo.fromBlock(b).changes, same(c));
  });

  testWidgets('任务卡显示改动区；撤销确认后 POST，成功变“已撤销”', (t) async {
    final api = _Api(() => _wire(undone: true));
    await _pump(t, api, JobBlock.fromJson(_wire()));
    expect(find.text('任务改了 2 个文件'), findsOneWidget);
    expect(find.text('out/result.csv'), findsOneWidget);
    expect(find.text('加了可执行'), findsOneWidget);
    await t.tap(find.text('撤销'));
    await t.pumpAndSettle();
    expect(find.text('撤销这个任务的文件改动？'), findsOneWidget);
    await t.tap(find.widgetWithText(PillButton, '撤销'));
    await t.pumpAndSettle();
    expect(api.posts, ['/api/jobs/j1/changes/undo']);
    expect(find.text('已撤销 2 个文件的改动'), findsOneWidget);
    expect(find.text('文件已回到任务开始前的样子'), findsOneWidget);
    expect(find.text('撤销'), findsNothing);
  });

  testWidgets('撤销冲突：toast 原因，卡不变', (t) async {
    final api = _Api(() => ApiError('这些文件之后又被改过，撤销会冲掉新的改动：run.sh', 409));
    await _pump(t, api, JobBlock.fromJson(_wire()));
    await t.tap(find.text('撤销'));
    await t.pumpAndSettle();
    await t.tap(find.widgetWithText(PillButton, '撤销'));
    await t.pumpAndSettle();
    expect(find.textContaining('之后又被改过'), findsOneWidget);
    expect(find.text('任务改了 2 个文件'), findsOneWidget);
    await t.pump(const Duration(seconds: 5));
    await t.pumpAndSettle();
  });

  testWidgets('没改文件：没有改动区', (t) async {
    final w = _wire()..remove('changes');
    await _pump(t, _Api(() => w), JobBlock.fromJson(w));
    expect(find.textContaining('改了'), findsNothing);
  });
}
