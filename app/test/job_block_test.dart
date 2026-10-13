// 后台任务卡（v1.19）：纯规则（状态词、用时、日志尾巴）+ 卡片行为——
// 运行中轮询进度、取消、结束后等服务器“接着说”完再让聊天页刷新一次；翻历史里已结束的卡不请求、不刷新。
import 'package:assistant/blocks/block_actions.dart';
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
  final List<Map<String, dynamic>> replies; // 依次返回；用完了重复最后一个
  final gets = <String>[];
  final posts = <String>[];

  @override
  Future<dynamic> get(String path) async {
    gets.add(path);
    return replies.length > 1 ? replies.removeAt(0) : replies.first;
  }

  @override
  Future<dynamic> post(String path, [Object? body]) async {
    posts.add(path);
    return _wire('cancelled', followup: 'pending', tail: '第 3 轮\nTerminated');
  }

  @override
  dynamic noSuchMethod(Invocation i) => throw UnimplementedError();
}

Map<String, dynamic> _wire(String state, {String followup = 'none', String tail = '', int elapsed = 5, int? code}) => {
      'id': 'j1', 'title': '训练模型', 'command': 'python train.py', 'state': state, 'exit_code': code,
      'followup': followup, 'elapsed': elapsed, 'tail': tail, 'started_at': '2026-10-12T02:00:00+00:00',
    };

const _running = JobBlock(id: 'j1', title: '训练模型', command: 'python train.py\n--epochs 3', state: 'running');

Future<int> _pump(WidgetTester tester, _Api api, JobBlock block) async {
  var settled = 0;
  tester.view.physicalSize = const Size(400, 800);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(ProviderScope(
    overrides: [apiProvider.overrideWithValue(api), cacheStoreProvider.overrideWithValue(MemoryCacheStore())],
    child: MaterialApp(
      theme: buildTheme(Brightness.light),
      home: Scaffold(
        body: StatefulBuilder(
          builder: (context, setState) => BlockActions(
            onJobSettled: () => setState(() => settled++),
            child: Padding(padding: const EdgeInsets.all(16), child: JobBlockView(block)),
          ),
        ),
      ),
    ),
  ));
  await tester.pump();
  return settled;
}

void main() {
  test('状态词、用时、日志尾巴', () {
    JobInfo info(String s, {int? code}) => JobInfo.fromJson(_wire(s, code: code));
    expect(jobStateLabel(info('done', code: 0)), '已完成');
    expect(jobStateLabel(info('failed', code: 3)), '失败 · 退出码 3');
    expect(jobStateLabel(info('timed_out', code: 124)), '超时被终止');
    expect(jobStateLabel(info('lost')), '中断了');
    expect(jobTone('failed'), JobTone.problem);
    expect(jobTone('cancelled'), JobTone.quiet);
    expect(jobTone('running'), JobTone.running);
    expect(jobDuration(const Duration(seconds: 9)), '9 秒');
    expect(jobDuration(const Duration(seconds: 65)), '1 分 05 秒');
    expect(jobDuration(const Duration(seconds: 3720)), '1 小时 02 分');
    expect(jobTailLines('a\nb\nc\nd\n\n', 2), 'c\nd');
    expect(JobInfo.fromJson(_wire('done', followup: 'pending')).awaitingReply, isTrue);
    expect(JobInfo.fromJson(_wire('done', followup: 'seen')).awaitingReply, isFalse);
    expect(Block.fromJson({'type': 'job', 'id': 'j', 'title': 't', 'command': 'c', 'state': 'failed', 'exit_code': 2}), isA<JobBlock>());
    expect(standsAlone(_running), isTrue);
  });

  test('护栏自动停：算问题、不叫“已取消”，原因进读屏（v1.20）', () {
    final stopped = JobInfo.fromJson({..._wire('cancelled', code: 143), 'stop_reason': '连续 20 分钟 没有任何新输出，判定卡住'});
    expect(stopped.autoStopped, isTrue);
    expect(jobStateLabel(stopped), '已自动停止');
    expect(jobTone(stopped.state, autoStopped: stopped.autoStopped), JobTone.problem);
    expect(jobSemantics(stopped), contains('已自动停止：连续 20 分钟'));
    final byUser = JobInfo.fromJson({..._wire('cancelled'), 'stop_reason': null});
    expect(byUser.autoStopped, isFalse);
    expect(jobStateLabel(byUser), '已取消');
    final b = Block.fromJson({'type': 'job', 'id': 'j', 'title': 't', 'command': 'c', 'state': 'cancelled', 'stop_reason': '输出超过 64 MB'}) as JobBlock;
    expect(JobInfo.fromBlock(b).autoStopped, isTrue);
    expect(JobInfo.fromBlock(b).withElapsed(const Duration(seconds: 3)).stopReason, '输出超过 64 MB');
  });

  test('谁停的：你停掉了 / 助手停掉了 / 老数据已取消（v2.25）', () {
    expect(jobStateLabel(JobInfo.fromJson({..._wire('cancelled'), 'stopped_by': 'user'})), '你停掉了');
    expect(jobStateLabel(JobInfo.fromJson({..._wire('cancelled'), 'stopped_by': 'agent'})), '助手停掉了');
    expect(jobStateLabel(JobInfo.fromJson({..._wire('cancelled'), 'stopped_by': 'x'})), '已取消');
    final guard = JobInfo.fromJson({..._wire('cancelled'), 'stopped_by': 'guard', 'stop_reason': '卡住'});
    expect(jobStateLabel(guard), '已自动停止');
    final b = Block.fromJson({'type': 'job', 'id': 'j', 'title': 't', 'command': 'c', 'state': 'cancelled', 'stopped_by': 'user'}) as JobBlock;
    expect(jobStateLabel(JobInfo.fromBlock(b).withElapsed(const Duration(seconds: 2))), '你停掉了');
  });

  testWidgets('运行中轮询 → 结束 → 等接着说完 → 刷新对话一次', (tester) async {
    final api = _Api([
      _wire('running', tail: '第 1 轮'),
      _wire('running', tail: '第 1 轮\n第 2 轮 loss=0.3', elapsed: 7),
      _wire('done', followup: 'pending', tail: '第 2 轮\n完成 acc=0.93', code: 0),
      _wire('done', followup: 'done', tail: '第 2 轮\n完成 acc=0.93', code: 0),
    ]);
    var settled = 0;
    tester.view.physicalSize = const Size(400, 800);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    await tester.pumpWidget(ProviderScope(
      overrides: [apiProvider.overrideWithValue(api), cacheStoreProvider.overrideWithValue(MemoryCacheStore())],
      child: MaterialApp(
        theme: buildTheme(Brightness.light),
        home: Scaffold(body: BlockActions(onJobSettled: () => settled++, child: const JobBlockView(_running))),
      ),
    ));
    await tester.pump();
    expect(find.text('训练模型'), findsOneWidget);
    expect(find.text('\$ python train.py'), findsOneWidget); // 只显示第一行
    expect(find.text('运行中'), findsOneWidget);
    expect(find.text('取消'), findsOneWidget);
    expect(find.text('第 1 轮'), findsOneWidget);
    await tester.pump(const Duration(seconds: 2));
    await tester.pump(const Duration(milliseconds: 300));
    expect(find.textContaining('loss=0.3'), findsOneWidget);
    await tester.pump(const Duration(seconds: 2));
    await tester.pump(const Duration(milliseconds: 300));
    expect(find.text('已完成 · 助手在看结果'), findsOneWidget);
    expect(find.text('完整日志'), findsOneWidget);
    expect(settled, 0); // 还在等服务器接着说
    await tester.pump(const Duration(seconds: 2));
    await tester.pump(const Duration(milliseconds: 300));
    expect(find.text('已完成'), findsOneWidget);
    expect(settled, 1);
    final n = api.gets.length;
    await tester.pump(const Duration(seconds: 6));
    expect(api.gets.length, n); // 停止轮询
    expect(settled, 1);
  });

  testWidgets('取消：调接口，状态变成已取消', (tester) async {
    final api = _Api([_wire('running', tail: '第 3 轮')]);
    await _pump(tester, api, _running);
    await tester.tap(find.text('取消'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 300));
    expect(api.posts, ['/api/jobs/j1/cancel']);
    expect(find.textContaining('已取消'), findsOneWidget);
    await tester.pumpWidget(const SizedBox()); // 停掉计时器
  });

  testWidgets('历史里已结束的卡：不请求、不刷新；失败用警示词', (tester) async {
    final api = _Api([_wire('failed')]);
    final settled = await _pump(
        tester,
        api,
        const JobBlock(id: 'j1', title: '装依赖', command: 'pip install torch', state: 'failed', exitCode: 1, tail: 'No space left on device'));
    await tester.pump(const Duration(seconds: 5));
    expect(api.gets, isEmpty);
    expect(settled, 0);
    expect(find.text('失败 · 退出码 1'), findsOneWidget);
    expect(find.text('No space left on device'), findsOneWidget);
    expect(find.text('取消'), findsNothing);
    await tester.tap(find.text('完整日志'));
    await tester.pumpAndSettle();
    expect(find.text('装依赖'), findsNWidgets(2)); // 卡片 + 日志弹层标题
  });

  testWidgets('护栏停掉的卡：警示状态词 + 日志下写原因', (tester) async {
    final api = _Api([_wire('cancelled')]);
    await _pump(
        tester,
        api,
        const JobBlock(id: 'j1', title: '爬取', command: 'python crawl.py', state: 'cancelled', exitCode: 143, tail: '第 37 页',
            stopReason: '连续 20 分钟 没有任何新输出，判定卡住'));
    expect(api.gets, isEmpty);
    expect(find.text('已自动停止'), findsOneWidget);
    expect(find.text('连续 20 分钟 没有任何新输出，判定卡住'), findsOneWidget);
    expect(find.text('完整日志'), findsOneWidget);
    expect(find.bySemanticsLabel(RegExp('已自动停止：连续 20 分钟')), findsOneWidget);
  });

  test('常驻任务（v1.80）：状态词、底部行、副标题、读屏', () {
    final run = JobInfo.fromJson({..._wire('running'), 'keep_alive': true, 'restarts': 2});
    expect(run.keepAlive, isTrue);
    expect(jobStateLabel(run), '常驻 · 运行中');
    expect(jobFootLabel(run), '常驻 · 运行中 · 已自动重启 2 次');
    expect(jobRowSubtitle(run), '常驻 · 已重启 2 次 · 运行 5 秒 · \$ python train.py');
    expect(jobSemantics(run), contains('常驻任务 训练模型'));
    final waiting = JobInfo.fromJson({..._wire('running'), 'keep_alive': true, 'restarts': 0, 'restart_at': '2026-10-13T04:00:00Z'});
    expect(jobStateLabel(waiting), '重启中');
    expect(jobFootLabel(waiting), '重启中');
    expect(jobRowSubtitle(waiting).startsWith('重启中 · 运行'), isTrue);
    expect(waiting.running, isTrue);
    final plain = JobInfo.fromJson(_wire('running'));
    expect(plain.keepAlive, isFalse);
    expect(jobFootLabel(plain), '运行中');
    expect(jobRowSubtitle(plain), '运行 5 秒 · \$ python train.py');
    final gaveUp = JobInfo.fromBlock(JobBlock.fromJson({'type': 'job', 'id': 'j1', 'title': 't', 'command': 'c', 'state': 'failed',
        'exit_code': 1, 'keep_alive': true, 'restarts': 5, 'stop_reason': '连续 6 次启动后不到 1 分钟就退出，已停止自动重启'}));
    expect(gaveUp.keepAlive, isTrue);
    expect(jobFootLabel(gaveUp), '失败 · 退出码 1 · 已自动重启 5 次');
  });

  test('前台转入后台（v2.04）：底部行、副标题、读屏，块 → 快照带过去', () {
    final run = JobInfo.fromJson({..._wire('running'), 'promoted': true});
    expect(run.promoted, isTrue);
    expect(jobFootLabel(run), '运行中 · 从前台转入');
    expect(jobRowSubtitle(run), '从前台转入 · 运行 5 秒 · \$ python train.py');
    expect(jobSemantics(run), contains('后台任务 训练模型（从前台转入），运行中'));
    expect(run.withElapsed(const Duration(seconds: 9)).promoted, isTrue);
    final done = JobInfo.fromBlock(JobBlock.fromJson({'type': 'job', 'id': 'j1', 'title': 'pip install torch',
        'command': 'pip install torch', 'state': 'done', 'exit_code': 0, 'promoted': true}));
    expect(done.promoted, isTrue);
    expect(jobFootLabel(done), '已完成 · 从前台转入');
    expect(JobInfo.fromJson(_wire('running')).promoted, isFalse);
  });
}
