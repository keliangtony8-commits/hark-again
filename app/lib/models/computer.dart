// 工作区的“电脑”（后端 app/computer.py，接口 GET/POST /api/projects/{ws}/computer[/restart]）：
// 容器状态、内存、磁盘、正在跑的后台任务。纯规则——状态词、说明行、内存比例、读屏句子；网页版 lib/computer.ts 同一套。
import '../ui/format.dart';
import 'job.dart';

class ComputerStatus {
  const ComputerStatus({required this.workspace, required this.state, this.memoryUsed, this.memoryLimit, this.startedAt,
      this.idleMinutes, this.outdated = false, this.diskUsed = 0, this.diskPartial = false, this.jobs = const []});

  factory ComputerStatus.fromJson(Map<String, dynamic> j) {
    final sb = (j['sandbox'] as Map?)?.cast<String, dynamic>() ?? const {};
    return ComputerStatus(
      workspace: j['workspace'] as String? ?? '',
      state: sb['state'] as String? ?? 'unreachable',
      memoryUsed: (sb['memory_used'] as num?)?.toInt(),
      memoryLimit: (sb['memory_limit'] as num?)?.toInt(),
      startedAt: DateTime.tryParse(sb['started_at'] as String? ?? '')?.toLocal(),
      idleMinutes: (sb['idle_minutes'] as num?)?.toInt(),
      outdated: sb['outdated'] == true,
      diskUsed: (j['disk_used'] as num?)?.toInt() ?? 0,
      diskPartial: j['disk_partial'] == true,
      jobs: [for (final x in (j['running_jobs'] as List? ?? const [])) JobInfo.fromJson((x as Map).cast<String, dynamic>())],
    );
  }

  final String workspace;

  /// running 运行中 / stopped 空闲休眠 / none 还没开过机 / unreachable 沙盒服务连不上
  final String state;
  final int? memoryUsed, memoryLimit, idleMinutes;
  final DateTime? startedAt;
  final bool outdated, diskPartial;
  final int diskUsed;
  final List<JobInfo> jobs;

  bool get running => state == 'running';
  bool get reachable => state != 'unreachable';
}

/// 内存吃到多少算紧张（条变警示色、说明行提醒）。
const computerMemoryTight = 0.85;

String computerStateLabel(String state) => switch (state) {
      'running' => '运行中',
      'stopped' => '休眠中',
      'none' => '还没开机',
      _ => '连不上沙盒',
    };

/// 内存占比（0–1）；不在跑或拿不到 → null（不画条）。
double? computerMemoryRatio(ComputerStatus s) {
  final u = s.memoryUsed, l = s.memoryLimit;
  if (!s.running || u == null || l == null || l <= 0) return null;
  return (u / l).clamp(0, 1).toDouble();
}

String _disk(ComputerStatus s) => '文件 ${formatSize(s.diskUsed)}${s.diskPartial ? '+' : ''}';

/// 状态下面那一行：在跑看内存，休眠/没开机说明什么时候会开，连不上说清是哪一环。磁盘始终在。
String computerDetail(ComputerStatus s) {
  final disk = _disk(s);
  return switch (s.state) {
    'running' => [
        if (s.memoryUsed != null)
          '内存 ${formatSize(s.memoryUsed!)}${s.memoryLimit != null ? ' / ${formatSize(s.memoryLimit!)}' : ''}',
        disk,
      ].join(' · '),
    'stopped' => '${s.idleMinutes != null ? '空闲 ${s.idleMinutes} 分钟自动休眠，' : ''}用到时自动开机 · $disk',
    'none' => '第一次跑命令时开机 · $disk',
    _ => '服务器上的沙盒服务没在跑，命令和后台任务暂时用不了 · $disk',
  };
}

/// 行尾小字：有任务在跑说几个；在跑但空闲说“空闲”；镜像更新过说“下次用到时更新”。
String? computerHint(ComputerStatus s) {
  if (s.jobs.isNotEmpty) return '${s.jobs.length} 个任务在跑';
  if (s.outdated && s.reachable) return '下次用到时更新';
  if (s.running) return '空闲';
  return null;
}

/// 重启确认里的说明。
String computerRestartText(ComputerStatus s) => [
      if (s.jobs.isNotEmpty) '会停掉 ${s.jobs.length} 个正在跑的后台任务。',
      '文件和装过的软件都在，下次用到时自动开机。',
    ].join();

/// 读屏一句话。
String computerSemantics(ComputerStatus s) => '电脑${computerStateLabel(s.state)}，${computerDetail(s)}'
    '${s.jobs.isEmpty ? '' : '，${s.jobs.length} 个后台任务在跑'}';
