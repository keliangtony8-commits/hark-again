// 后台任务（后端 app/jobs.py，接口 /api/jobs）：聊天里的任务卡用的纯规则——状态文案、用时、日志尾巴、轮询何时停。
// 网页版 frontend/src/lib/jobs.ts 同一套规则。
import 'block.dart';

const jobFinal = {'done', 'failed', 'timed_out', 'cancelled', 'lost'};

/// /api/jobs/{id} 的一次快照。
class JobInfo {
  const JobInfo({required this.id, required this.title, required this.command, required this.state,
      this.exitCode, this.followup = 'none', required this.elapsed, this.tail = '', this.startedAt, this.finishedAt,
      this.stopReason, this.keepAlive = false, this.restarts = 0, this.restartAt});

  factory JobInfo.fromJson(Map<String, dynamic> j) => JobInfo(
      id: j['id'] as String? ?? '',
      title: j['title'] as String? ?? '后台任务',
      command: j['command'] as String? ?? '',
      state: j['state'] as String? ?? 'running',
      exitCode: (j['exit_code'] as num?)?.toInt(),
      followup: j['followup'] as String? ?? 'none',
      elapsed: Duration(seconds: (j['elapsed'] as num?)?.toInt() ?? 0),
      tail: j['tail'] as String? ?? '',
      startedAt: DateTime.tryParse(j['started_at'] as String? ?? '')?.toLocal(),
      finishedAt: DateTime.tryParse(j['finished_at'] as String? ?? '')?.toLocal(),
      stopReason: j['stop_reason'] as String?,
      keepAlive: j['keep_alive'] as bool? ?? false,
      restarts: (j['restarts'] as num?)?.toInt() ?? 0,
      restartAt: DateTime.tryParse(j['restart_at'] as String? ?? '')?.toLocal());

  /// 还没问过服务器时，用消息里落库的块先画出来。
  factory JobInfo.fromBlock(JobBlock b) => JobInfo(
      id: b.id,
      title: b.title,
      command: b.command,
      state: b.state,
      exitCode: b.exitCode,
      elapsed: b.startedAt == null ? Duration.zero : (b.finishedAt ?? DateTime.now()).difference(b.startedAt!),
      tail: b.tail ?? '',
      startedAt: b.startedAt,
      finishedAt: b.finishedAt,
      stopReason: b.stopReason,
      keepAlive: b.keepAlive,
      restarts: b.restarts);

  /// 换个用时（卡片跳秒用），其余不变。
  JobInfo withElapsed(Duration d) => JobInfo(
      id: id, title: title, command: command, state: state, exitCode: exitCode, followup: followup, elapsed: d,
      tail: tail, startedAt: startedAt, finishedAt: finishedAt, stopReason: stopReason, keepAlive: keepAlive,
      restarts: restarts, restartAt: restartAt);

  final String id, title, command, state, followup, tail;
  final String? stopReason;
  final int? exitCode;
  final Duration elapsed;
  final DateTime? startedAt, finishedAt;

  /// v1.80 常驻任务（后端 app/job_restart.py）：意外退出自动重启；restarts 重启过几次；
  /// restartAt 不为空 = 进程刚退出、正在等这个时刻重启（state 仍是 running）。
  final bool keepAlive;
  final int restarts;
  final DateTime? restartAt;

  bool get running => !jobFinal.contains(state);

  /// 服务器护栏停的（连续没输出判定卡住 / 输出过大）：算出了问题，不是“已取消”。
  bool get autoStopped => state == 'cancelled' && (stopReason ?? '').isNotEmpty;

  /// 结束了，服务器还要在这段对话里接着说一轮（worker 几秒内跑）：卡片继续问，等它说完再刷新对话。
  bool get awaitingReply => !running && followup == 'pending';
}

enum JobTone { running, ok, problem, quiet }

JobTone jobTone(String state, {bool autoStopped = false}) => switch (state) {
      _ when autoStopped => JobTone.problem,
      'done' => JobTone.ok,
      'failed' || 'timed_out' || 'lost' => JobTone.problem,
      'cancelled' => JobTone.quiet,
      _ => JobTone.running,
    };

/// 卡头右侧的状态词。失败带退出码（0 和取消不带）。
String jobStateLabel(JobInfo j) => switch (j.state) {
      'running' when j.keepAlive => j.restartAt != null ? '重启中' : '常驻 · 运行中',
      'running' => '运行中',
      'done' => '已完成',
      'failed' => j.exitCode == null ? '失败' : '失败 · 退出码 ${j.exitCode}',
      'timed_out' => '超时被终止',
      'cancelled' => j.autoStopped ? '已自动停止' : '已取消',
      'lost' => '中断了',
      _ => j.state,
    };

/// 卡片底部那行：状态词 · 已自动重启 N 次（常驻）· 助手在看结果（等它接着说）。
String jobFootLabel(JobInfo j) => [
      jobStateLabel(j),
      if (j.keepAlive && j.restarts > 0) '已自动重启 ${j.restarts} 次',
      if (j.awaitingReply) '助手在看结果',
    ].join(' · ');

/// “这台电脑”里运行中任务那行的副标题：常驻的先说清（常驻 / 重启中、重启过几次），再是用时和命令。
String jobRowSubtitle(JobInfo j) => [
      if (j.keepAlive) j.restartAt != null ? '重启中' : '常驻',
      if (j.keepAlive && j.restarts > 0) '已重启 ${j.restarts} 次',
      '运行 ${jobDuration(j.elapsed)}',
      '\$ ${j.command.split('\n').first}',
    ].join(' · ');

/// 用时：12 秒 / 3 分 05 秒 / 1 小时 02 分（与后端 duration_text 同档位，分秒补零好对齐）。
String jobDuration(Duration d) {
  final s = d.inSeconds < 0 ? 0 : d.inSeconds;
  if (s < 60) return '$s 秒';
  String two(int n) => n.toString().padLeft(2, '0');
  if (s < 3600) return '${s ~/ 60} 分 ${two(s % 60)} 秒';
  return '${s ~/ 3600} 小时 ${two(s % 3600 ~/ 60)} 分';
}

/// 日志最后 [lines] 行（去掉末尾空行）。卡片上只看尾巴，完整的在“完整日志”里。
String jobTailLines(String tail, int lines) {
  final all = tail.trimRight().split('\n');
  return all.length <= lines ? all.join('\n') : all.sublist(all.length - lines).join('\n');
}

/// 读屏：一句话说清这张卡。
String jobSemantics(JobInfo j) =>
    '${j.keepAlive ? '常驻任务' : '后台任务'} ${j.title}，${jobStateLabel(j)}${j.autoStopped ? '：${j.stopReason}' : ''}'
    '${j.keepAlive && j.restarts > 0 ? '，已自动重启 ${j.restarts} 次' : ''}，用时 ${jobDuration(j.elapsed)}';
