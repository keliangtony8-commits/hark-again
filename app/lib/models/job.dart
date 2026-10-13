// 后台任务（后端 app/jobs.py，接口 /api/jobs）：聊天里的任务卡用的纯规则——状态文案、用时、日志尾巴、轮询何时停。
// 网页版 frontend/src/lib/jobs.ts 同一套规则。
import '../ui/format.dart';
import 'block.dart';
import 'changes.dart';
import 'job_disk.dart';

export 'job_disk.dart';

const jobFinal = {'done', 'failed', 'timed_out', 'cancelled', 'lost'};

/// /api/jobs/{id} 的一次快照。
class JobInfo {
  const JobInfo({required this.id, required this.title, required this.command, required this.state,
      this.exitCode, this.followup = 'none', required this.elapsed, this.tail = '', this.startedAt, this.finishedAt,
      this.stopReason, this.keepAlive = false, this.restarts = 0, this.restartAt, this.usage, this.memoryMax,
      this.memoryPeak, this.box, this.disk, this.promoted = false, this.changes});

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
      restartAt: DateTime.tryParse(j['restart_at'] as String? ?? '')?.toLocal(),
      usage: JobUsage.tryParse(j['usage']),
      memoryMax: _bytes(j['memory_max']),
      memoryPeak: _bytes(j['memory_peak']),
      box: JobBox.tryParse(j['box']),
      disk: JobDisk.tryParse(j['disk']),
      promoted: j['promoted'] as bool? ?? false,
      changes: ChangesBlock.tryParse(j['changes']));

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
      restarts: b.restarts,
      memoryMax: b.memoryMax,
      memoryPeak: b.memoryPeak,
      disk: b.disk,
      promoted: b.promoted,
      changes: b.changes);

  /// 换个用时（卡片跳秒用），其余不变。
  JobInfo withElapsed(Duration d) => JobInfo(
      id: id, title: title, command: command, state: state, exitCode: exitCode, followup: followup, elapsed: d,
      tail: tail, startedAt: startedAt, finishedAt: finishedAt, stopReason: stopReason, keepAlive: keepAlive,
      restarts: restarts, restartAt: restartAt, usage: usage, memoryMax: memoryMax, memoryPeak: memoryPeak, box: box,
      disk: disk, promoted: promoted, changes: changes);

  /// v2.18 它改了哪些文件（结束了才有；可撤销）。规则在 models/changes.dart。
  final ChangesBlock? changes;

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

  /// v1.90 现在占多少（后端 app/job_usage.py）：只有进程确实在跑、问得到沙盒时才有；null = 不知道（不是 0）。
  final JobUsage? usage;

  /// v1.92（后端 app/job_memory.py）：给它单独定的内存上限、采样看到的峰值（字节，null = 没设 / 没采到）；
  /// box = 整台沙盒此刻的内存（只有在跑时才有），快满了卡片提醒。
  final int? memoryMax, memoryPeak;
  final JobBox? box;

  /// v1.96 磁盘账（后端 app/job_disk.py）：运行中现数，结束了是结算时的；null = 没数（老任务 / 工作区没了）。
  final JobDisk? disk;

  /// v2.04 前台命令到点没跑完、转进后台接着跑的（后端 jobs.adopt）：卡上标 [jobPromotedLabel]。
  final bool promoted;

  bool get running => !jobFinal.contains(state);

  /// 服务器护栏停的（连续没输出判定卡住 / 输出过大）：算出了问题，不是“已取消”。
  bool get autoStopped => state == 'cancelled' && (stopReason ?? '').isNotEmpty;

  /// 卡片日志下面要写原因：护栏停的、内存超限 / 打满被结束的、常驻服务放弃重启的。
  bool get showsReason => !running && (stopReason ?? '').isNotEmpty;

  /// 内存到了自己上限的 [jobMemNear] 以上（再涨就会被结束）。
  bool get memoryNear => memoryMax != null && usage != null && usage!.memory >= memoryMax! * jobMemNear;

  /// 在跑，且整台沙盒内存用到 [jobBoxTight] 以上。
  bool get boxTight => running && box != null && box!.used >= box!.limit * jobBoxTight;

  /// 结束了，服务器还要在这段对话里接着说一轮（worker 几秒内跑）：卡片继续问，等它说完再刷新对话。
  bool get awaitingReply => !running && followup == 'pending';
}

int? _bytes(Object? v) => v is num && v > 0 ? v.toInt() : null;

/// 整台沙盒的内存（不含可回收的文件缓存）。
class JobBox {
  const JobBox({required this.used, required this.limit});

  static JobBox? tryParse(Object? raw) {
    if (raw is! Map) return null;
    final used = raw['used'], limit = raw['limit'];
    if (used is! num || limit is! num || used < 0 || limit <= 0) return null;
    return JobBox(used: used.toInt().clamp(0, limit.toInt()), limit: limit.toInt());
  }

  final int used, limit;
  int get percent => (used * 100 / limit).round();
}

/// 到自己内存上限的这个比例，卡片上的内存字变成警示色（同后端 job_memory.NEAR）。
const jobMemNear = 0.8;

/// 整台沙盒内存用到这个比例，卡片提醒“快满了”（同后端 job_memory.TIGHT）。
const jobBoxTight = 0.9;

/// 卡片上“快满了”那句。
String jobBoxLabel(JobBox b) => '这台电脑内存已用 ${b.percent}%（${formatSize(b.used)} / ${formatSize(b.limit)}），再涨系统会强制结束进程';

/// 一个后台任务（整个进程组）此刻的资源占用。cpu = 占这台电脑 CPU 配额的百分比（和电脑卡的 CPU 一个口径）。
class JobUsage {
  const JobUsage({required this.cpu, required this.cpuSeconds, required this.memory, required this.processes});

  /// 字段缺 / 类型不对 / 负数 / 0 个进程 → null（宁可不显示也不显示错的）。
  static JobUsage? tryParse(Object? raw) {
    if (raw is! Map) return null;
    final cpu = raw['cpu'], secs = raw['cpu_seconds'], mem = raw['memory'], n = raw['processes'];
    if (cpu is! num || secs is! num || mem is! num || n is! num) return null;
    if (cpu < 0 || secs < 0 || mem < 0 || n < 1) return null;
    return JobUsage(cpu: cpu.toDouble(), cpuSeconds: secs.toDouble(), memory: mem.toInt(), processes: n.toInt());
  }

  final double cpu, cpuSeconds;
  final int memory, processes;

  @override
  bool operator ==(Object other) =>
      other is JobUsage && other.cpu == cpu && other.cpuSeconds == cpuSeconds && other.memory == memory && other.processes == processes;

  @override
  int get hashCode => Object.hash(cpu, cpuSeconds, memory, processes);
}

/// CPU 到这么高（占配额 %）卡片上的条变成警示色：基本吃满了，别的命令会跟着变慢。
const jobCpuHot = 90.0;

/// CPU 百分比：≥10 取整，<10 留一位（0.4%），0 写 0%。
String jobCpuLabel(double cpu) => cpu >= 10 || cpu == 0 ? '${cpu.round()}%' : '${cpu.toStringAsFixed(1)}%';

/// 卡片 / 任务行上的一段：CPU 35% · 内存 120.0 MB · 3 个进程（只有 1 个进程时不写）。
String jobUsageLabel(JobUsage u) => [
      'CPU ${jobCpuLabel(u.cpu)}',
      '内存 ${formatSize(u.memory)}',
      if (u.processes > 1) '${u.processes} 个进程',
    ].join(' · ');

/// 任务卡 CPU 条右边那段：内存 120.0 MB（设了上限：120.0 MB / 512.0 MB）· 3 个进程。
String jobMemoryLabel(JobUsage u, {int? max}) => [
      '内存 ${formatSize(u.memory)}${max != null ? ' / ${formatSize(max)}' : ''}',
      if (u.processes > 1) '${u.processes} 个进程',
    ].join(' · ');

/// 读屏：占用 CPU 35%，内存 120.0 MB，3 个进程。
String jobUsageSemantics(JobUsage u) =>
    '占用 CPU ${jobCpuLabel(u.cpu)}，内存 ${formatSize(u.memory)}${u.processes > 1 ? '，${u.processes} 个进程' : ''}';

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

/// 前台命令转进后台的任务，卡片底部和“这台电脑”里都标这一句（网页版 lib/jobs.ts 同一句）。
const jobPromotedLabel = '从前台转入';

/// 卡片底部那行：状态词 · 从前台转入 · 已自动重启 N 次（常驻）· 助手在看结果（等它接着说）。
String jobFootLabel(JobInfo j) => [
      jobStateLabel(j),
      if (j.promoted) jobPromotedLabel,
      if (j.keepAlive && j.restarts > 0) '已自动重启 ${j.restarts} 次',
      if (!j.running && j.memoryPeak != null) '内存峰值 ${formatSize(j.memoryPeak!)}',
      if (j.awaitingReply) '助手在看结果',
    ].join(' · ');

/// “这台电脑”里运行中任务那行的副标题：常驻的先说清（常驻 / 重启中、重启过几次），再是用时和命令。
String jobRowSubtitle(JobInfo j) => [
      if (j.keepAlive) j.restartAt != null ? '重启中' : '常驻',
      if (j.keepAlive && j.restarts > 0) '已重启 ${j.restarts} 次',
      if (j.promoted) jobPromotedLabel,
      '运行 ${jobDuration(j.elapsed)}',
      if (j.usage != null) jobUsageLabel(j.usage!),
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
    '${j.keepAlive ? '常驻任务' : '后台任务'} ${j.title}${j.promoted ? '（$jobPromotedLabel）' : ''}，${jobStateLabel(j)}${j.showsReason ? '：${j.stopReason}' : ''}'
    '${j.keepAlive && j.restarts > 0 ? '，已自动重启 ${j.restarts} 次' : ''}，用时 ${jobDuration(j.elapsed)}'
    '${j.running && j.usage != null ? '，${jobUsageSemantics(j.usage!)}' : ''}'
    '${j.running && j.memoryMax != null ? '，内存上限 ${formatSize(j.memoryMax!)}' : ''}'
    '${j.boxTight ? '，${jobBoxLabel(j.box!)}' : ''}'
    '${jobDiskShown(j.disk) ? '，${jobDiskSemantics(j.disk!)}' : ''}'
    '${jobChangesShown(j.changes) ? '，${changesTitle(j.changes!, scope: ChangesScope.job)}' : ''}';
