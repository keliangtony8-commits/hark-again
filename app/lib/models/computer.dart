// 工作区的“电脑”（后端 app/computer.py，接口 GET/POST /api/projects/{ws}/computer[/restart]）：
// 容器状态、CPU/内存、磁盘（按用途拆开）、正在跑的程序和后台任务、装过的工具、内存打满被杀过几次（v1.27）。纯规则——状态词、说明行、内存比例、读屏句子；网页版 lib/computer.ts 同一套。
import '../ui/format.dart';
import 'job.dart';
import 'preview.dart';

class ComputerStatus {
  const ComputerStatus({required this.workspace, required this.state, this.memoryUsed, this.memoryLimit, this.startedAt,
      this.idleMinutes, this.outdated = false, this.diskUsed = 0, this.diskPartial = false, this.jobs = const [],
      this.cpuPercent, this.oomKills = 0, this.processes = const [], this.storage = ComputerStorage.empty, this.tools = const [], this.ports = const [], this.diskLimit, this.diskLevel = 'off'});

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
      diskLimit: (j['disk_limit'] as num?)?.toInt(),
      diskLevel: j['disk_level'] as String? ?? 'off',
      jobs: [for (final x in (j['running_jobs'] as List? ?? const [])) JobInfo.fromJson((x as Map).cast<String, dynamic>())],
      cpuPercent: (sb['cpu_percent'] as num?)?.toDouble(),
      oomKills: (sb['oom_kills'] as num?)?.toInt() ?? 0,
      processes: [
        for (final x in (sb['processes'] as List? ?? const []))
          if (x is Map) ComputerProcess.fromJson(x.cast<String, dynamic>())
      ],
      storage: ComputerStorage.fromJson((j['storage'] as Map?)?.cast<String, dynamic>() ?? const {}),
      tools: [
        for (final x in (j['tools'] as List? ?? const []))
          if (x is Map) InstalledTool.fromJson(x.cast<String, dynamic>())
      ],
      ports: [
        for (final x in (j['ports'] as List? ?? const []))
          if (x is Map) ListeningPort.fromJson(x.cast<String, dynamic>())
      ],
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
  final double? cpuPercent;

  /// 这次开机以来内存超上限、被系统强制结束的程序个数（容器 cgroup 的 oom_kill）。
  final int oomKills;
  final List<ComputerProcess> processes;
  final ComputerStorage storage;
  final List<InstalledTool> tools;

  /// 在监听的端口（v1.30，只在运行中时有）：旁边“预览”= POST …/computer/preview 签链接。
  final List<ListeningPort> ports;

  /// 磁盘配额（v1.31，服务器 app/quota.py）：上限字节（null = 不限）；
  /// 档位 ok / tight（≥85%，提醒）/ full（满了：新文件写不进、后台任务会被停）/ off。
  final int? diskLimit;
  final String diskLevel;
  bool get diskFull => diskLevel == 'full';
  bool get diskTight => diskLevel == 'tight' || diskFull;

  bool get running => state == 'running';
  bool get reachable => state != 'unreachable';
}

/// 正在跑的一个程序（按 CPU 排）。
class ComputerProcess {
  const ComputerProcess({required this.pid, required this.cpu, required this.memory, required this.elapsed, required this.command});
  factory ComputerProcess.fromJson(Map<String, dynamic> j) => ComputerProcess(
        pid: (j['pid'] as num?)?.toInt() ?? 0,
        cpu: (j['cpu'] as num?)?.toDouble() ?? 0,
        memory: (j['memory'] as num?)?.toInt() ?? 0,
        elapsed: (j['elapsed'] as num?)?.toInt() ?? 0,
        command: j['command'] as String? ?? '',
      );
  final int pid, memory, elapsed;
  final double cpu;
  final String command;
}

/// 磁盘按用途拆开（字节）。cleanable = 一键清理能腾出的（长输出存档 + 已结束任务日志 + 下载缓存）。
class ComputerStorage {
  const ComputerStorage(
      {this.files = 0, this.installed = 0, this.logs = 0, this.spill = 0, this.cache = 0, this.cleanable = 0});
  factory ComputerStorage.fromJson(Map<String, dynamic> j) {
    int n(String k) => (j[k] as num?)?.toInt() ?? 0;
    return ComputerStorage(
        files: n('files'), installed: n('installed'), logs: n('logs'), spill: n('spill'), cache: n('cache'), cleanable: n('cleanable'));
  }
  static const empty = ComputerStorage();
  final int files, installed, logs, spill, cache, cleanable;
}

/// 用户级装过的工具（pip / npm -g），不含镜像预装。
class InstalledTool {
  const InstalledTool({required this.kind, required this.name, this.version = ''});
  factory InstalledTool.fromJson(Map<String, dynamic> j) =>
      InstalledTool(kind: j['kind'] as String? ?? '', name: j['name'] as String? ?? '', version: j['version'] as String? ?? '');
  final String kind, name, version;
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

String _disk(ComputerStatus s) => '文件 ${formatSize(s.diskUsed)}${s.diskPartial ? '+' : ''}'
    '${s.diskLimit != null ? ' / ${formatSize(s.diskLimit!)}' : ''}';

/// 状态下面那一行：在跑看内存，休眠/没开机说明什么时候会开，连不上说清是哪一环。磁盘始终在。
String computerDetail(ComputerStatus s) {
  final disk = _disk(s);
  return switch (s.state) {
    'running' => [
        if (s.cpuPercent != null) 'CPU ${s.cpuPercent!.round()}%',
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
  if (s.diskFull) return '磁盘满了';
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

/// 内存打满被杀过：状态块里的一行警示。没有 → null。
String? computerOomNote(ComputerStatus s) {
  if (!s.running || s.oomKills <= 0) return null;
  final cap = s.memoryLimit != null ? '（上限 ${formatSize(s.memoryLimit!)}）' : '';
  return '内存不够，系统强制结束过 ${s.oomKills} 个程序$cap。分批处理或重启能缓过来';
}

/// 磁盘占上限的比例（0–1）；不限 → null（不画条）。
double? computerDiskRatio(ComputerStatus s) {
  final l = s.diskLimit;
  if (l == null || l <= 0) return null;
  return (s.diskUsed / l).clamp(0, 1).toDouble();
}

/// 配额那一行的标题：“已用 2.6 GB，上限 3 GB”。
String computerDiskLine(ComputerStatus s) =>
    '已用 ${formatSize(s.diskUsed)}${s.diskPartial ? '+' : ''}，上限 ${formatSize(s.diskLimit ?? 0)}';

/// 快满 / 满了的一句；平时 null。
String? computerDiskNote(ComputerStatus s) => switch (s.diskLevel) {
      'full' => '满了：新文件写不进，后台任务会被停下。清理一下，或删掉不要的文件',
      'tight' => '快满了：满了以后新文件写不进、后台任务会被停下',
      _ => null,
    };

/// 程序行：标题是命令（去掉 /usr/bin/ 之类的路径），副标题是 CPU · 内存 · 运行多久。
String processTitle(ComputerProcess p) {
  final c = p.command.trim();
  final sp = c.indexOf(' ');
  final head = sp < 0 ? c : c.substring(0, sp);
  return head.split('/').last + (sp < 0 ? '' : c.substring(sp));
}

String processLine(ComputerProcess p) =>
    'CPU ${p.cpu.round()}% · 内存 ${formatSize(p.memory)} · 运行 ${jobDuration(Duration(seconds: p.elapsed))}';

/// 磁盘一节的行：(键, 名字, 说明, 字节)，0 字节的不列（文件始终列）。
List<(String, String, String, int)> storageRows(ComputerStorage st) => [
      ('files', '文件', '你和我放进来的', st.files),
      if (st.installed > 0) ('installed', '装的软件', 'pip / npm 装进 ~/.local 的', st.installed),
      if (st.logs > 0) ('logs', '任务日志', '后台任务的完整输出', st.logs),
      if (st.spill > 0) ('spill', '长输出存档', '太长没塞进对话的命令输出', st.spill),
      if (st.cache > 0) ('cache', '下载缓存', 'pip / npm 的缓存', st.cache),
    ];

/// 标题行“清理”按钮的字；没东西可清 → null（不给按钮）。
String? cleanupLabel(ComputerStorage st) => st.cleanable > 0 ? '清理 ${formatSize(st.cleanable)}' : null;

const cleanupText = '删掉长输出存档、已结束任务的完整日志和下载缓存。文件、装的软件、正在跑的任务都不动；聊天里的任务卡照常能看结论。';

String cleanupDone(int freed) => freed > 0 ? '腾出了 ${formatSize(freed)}' : '没有可清理的了';

/// 工具行的副标题：“pip 12 个 · npm 2 个”。
String toolsSummary(List<InstalledTool> tools) {
  if (tools.isEmpty) return '还没装过，用到时我会 pip / npm 装进来';
  final pip = tools.where((t) => t.kind == 'pip').length, npm = tools.length - pip;
  return [if (pip > 0) 'pip $pip 个', if (npm > 0) 'npm $npm 个'].join(' · ');
}
