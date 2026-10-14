// 工作区的“电脑”（后端 app/computer.py，接口 GET/POST /api/projects/{ws}/computer[/restart]）：
// 容器状态、CPU/内存、磁盘（按用途拆开）、正在跑的程序和后台任务、装过的工具、内存打满被杀过几次（v1.27）、常驻服务健康（v1.82）。纯规则——状态词、说明行、内存比例、读屏句子；网页版 lib/computer.ts 同一套。
import '../ui/format.dart';
import 'job.dart';
import 'preview.dart';

class ComputerStatus {
  const ComputerStatus({required this.workspace, required this.state, this.memoryUsed, this.memoryLimit, this.startedAt,
      this.idleMinutes, this.outdated = false, this.diskUsed = 0, this.diskPartial = false, this.jobs = const [],
      this.cpuPercent, this.oomKills = 0, this.processes = const [], this.storage = ComputerStorage.empty, this.tools = const [], this.ports = const [], this.diskLimit, this.diskLevel = 'off', this.stoppedBy, this.services = const [], this.memory, this.diskJobs = const [], this.machine});

  factory ComputerStatus.fromJson(Map<String, dynamic> j) {
    final sb = (j['sandbox'] as Map?)?.cast<String, dynamic>() ?? const {};
    return ComputerStatus(
      workspace: j['workspace'] as String? ?? '',
      state: sb['state'] as String? ?? 'unreachable',
      memoryUsed: (sb['memory_used'] as num?)?.toInt(),
      memoryLimit: (sb['memory_limit'] as num?)?.toInt(),
      startedAt: DateTime.tryParse(sb['started_at'] as String? ?? '')?.toLocal(),
      idleMinutes: (sb['idle_minutes'] as num?)?.toInt(),
      stoppedBy: switch (sb['stopped_by']) { 'idle' => ComputerStopReason.idle, 'room' => ComputerStopReason.room, _ => null },
      outdated: sb['outdated'] == true,
      diskUsed: (j['disk_used'] as num?)?.toInt() ?? 0,
      diskPartial: j['disk_partial'] == true,
      diskLimit: (j['disk_limit'] as num?)?.toInt(),
      diskLevel: j['disk_level'] as String? ?? 'off',
      jobs: [for (final x in (j['running_jobs'] as List? ?? const [])) JobInfo.fromJson((x as Map).cast<String, dynamic>())],
      services: [
        for (final x in (j['services'] as List? ?? const []))
          if (x is Map) ServiceInfo.fromJson(x.cast<String, dynamic>())
      ],
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
      memory: j['memory'] is Map ? MemoryView.fromJson((j['memory'] as Map).cast<String, dynamic>()) : null,
      diskJobs: [
        for (final x in (j['disk_jobs'] as List? ?? const []))
          if (x is Map) ?DiskJob.tryParse(x.cast<String, dynamic>())
      ],
      machine: j['machine'] is Map ? MachineInfo.fromJson((j['machine'] as Map).cast<String, dynamic>()) : null,
    );
  }

  final String workspace;

  /// running 运行中 / stopped 空闲休眠 / none 还没开过机 / unreachable 沙盒服务连不上
  final String state;
  final int? memoryUsed, memoryLimit, idleMinutes;

  /// 休眠的原因（v1.74，只在 stopped 且是服务器停的时有；沙盒服务重启后不记得 → null）。
  final ComputerStopReason? stoppedBy;
  final DateTime? startedAt;
  final bool outdated, diskPartial;
  final int diskUsed;
  /// 正在跑的普通后台任务（常驻服务不在这里，见 [services]）。
  final List<JobInfo> jobs;

  /// v1.82 常驻服务（后端 app/services.py）：在跑的 + 最近 24 小时意外结束的（放弃自动重启了不该悄悄消失）。
  final List<ServiceInfo> services;
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

  /// v1.94 内存去哪了（服务器 app/memory_view.py）：只在运行中有。
  final MemoryView? memory;

  /// v1.98 最近 7 天谁写得最多（服务器 job_disk.leaders）：从大到小，最多 5 个；不用开机。
  final List<DiskJob> diskJobs;

  /// v2.85 整台服务器（后端 app/machine.py）：只在个人工作区有；项目的电脑 null。
  final MachineInfo? machine;
  bool get diskFull => diskLevel == 'full';
  bool get diskTight => diskLevel == 'tight' || diskFull;

  bool get running => state == 'running';
  bool get reachable => state != 'unreachable';

  /// 还活着（在跑或等自动重启）的常驻服务个数 / 已经停了（放弃自动重启）的个数。
  int get liveServices => services.where((v) => v.health != ServiceHealth.gaveUp).length;
  int get deadServices => services.length - liveServices;

  /// 状态会自己变（有任务在跑、服务在跑或等重启）：该轮询。
  bool get busy => jobs.isNotEmpty || liveServices > 0;
}

/// 常驻服务的健康：up 在跑 / restarting 进程退出了、等自动重启 / gaveUp 连续崩溃已停止自动重启（或别的意外结束）。
enum ServiceHealth { up, restarting, gaveUp }

/// 一个常驻服务（keep_alive 后台任务）：任务本身 + 健康、本次运行多久、它在监听的端口。
class ServiceInfo {
  const ServiceInfo({required this.job, required this.health, this.ports = const [], this.uptime, this.earlierStops = 0});
  factory ServiceInfo.fromJson(Map<String, dynamic> j) => ServiceInfo(
        job: JobInfo.fromJson(j),
        health: switch (j['health']) { 'up' => ServiceHealth.up, 'restarting' => ServiceHealth.restarting, _ => ServiceHealth.gaveUp },
        ports: [for (final x in (j['ports'] as List? ?? const [])) if (x is num) x.toInt()],
        uptime: j['uptime'] is num ? Duration(seconds: (j['uptime'] as num).toInt()) : null,
        earlierStops: (j['earlier_stops'] as num?)?.toInt() ?? 0,
      );
  final JobInfo job;

  /// v2.85 同名同命令的旧停止记录合进这一行（后端 services.merge）：24 小时内之前意外停过几次。
  final int earlierStops;
  final ServiceHealth health;
  final List<int> ports;
  final Duration? uptime;
}

/// 服务行的副标题：在跑 → 运行多久 · 端口 · 重启过几次；等重启 → 几秒后重启 · 上次退出码；停了 → 原因。
String serviceLine(ServiceInfo v, {DateTime? now}) {
  final j = v.job;
  final restarted = j.restarts > 0 ? '已重启 ${j.restarts} 次' : null;
  return switch (v.health) {
    ServiceHealth.up => [
        '运行 ${jobDuration(v.uptime ?? j.elapsed)}',
        if (v.ports.isNotEmpty) '端口 ${v.ports.join('、')}',
        if (j.usage != null) jobUsageLabel(j.usage!),
        ?restarted,
        ?_earlier(v),
      ].join(' · '),
    ServiceHealth.restarting => [
        _restartIn(j.restartAt, now ?? DateTime.now()),
        if (j.exitCode != null) '上次退出码 ${j.exitCode}',
        ?restarted,
      ].join(' · '),
    ServiceHealth.gaveUp =>
      (j.stopReason ?? '').isNotEmpty ? j.stopReason! : '意外退出${j.exitCode != null ? '（退出码 ${j.exitCode}）' : ''}',
  };
}

String? _earlier(ServiceInfo v) => v.earlierStops > 0 ? '24 小时内停过 ${v.earlierStops} 次' : null;

String _restartIn(DateTime? at, DateTime now) {
  final s = at == null ? 0 : at.difference(now).inSeconds;
  return s <= 1 ? '马上重启' : '${jobDuration(Duration(seconds: s))}后重启';
}

/// 行尾按钮：在跑 → 重启（改了代码要生效）；等重启 → 立即重启；停了 → 重新启动。
String serviceAction(ServiceHealth h) => switch (h) {
      ServiceHealth.up => '重启',
      ServiceHealth.restarting => '立即重启',
      ServiceHealth.gaveUp => '重新启动',
    };

/// 读屏一句：名字，健康，副标题。
String serviceSemantics(ServiceInfo v) => '常驻服务 ${v.job.title}，'
    '${switch (v.health) { ServiceHealth.up => '运行中', ServiceHealth.restarting => '等待自动重启', ServiceHealth.gaveUp => '已停止' }}，'
    '${serviceLine(v)}';

/// 电脑为什么休眠：idle 空闲太久；room 同时开机的电脑到上限，给正在用的其它工作区腾内存（sandbox/runner.py MAX_RUNNING）。
enum ComputerStopReason { idle, room }

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
    'stopped' => '${_sleepReason(s)}用到时自动开机 · $disk',
    'none' => '第一次跑命令时开机 · $disk',
    _ => '服务器上的沙盒服务没在跑，命令和后台任务暂时用不了 · $disk',
  };
}

String _sleepReason(ComputerStatus s) => switch (s.stoppedBy) {
      ComputerStopReason.room => '给正在用的其它工作区腾内存，先休眠了，',
      _ when s.idleMinutes != null => '空闲 ${s.idleMinutes} 分钟自动休眠，',
      _ => '',
    };

/// 行尾小字是不是警示（磁盘满、服务停了）。
bool computerHintWarn(ComputerStatus s) => s.diskFull || s.deadServices > 0;

/// 行尾小字：服务停了先说（v1.82）；有任务在跑说几个；在跑但空闲说“空闲”；镜像更新过说“下次用到时更新”。
String? computerHint(ComputerStatus s) {
  if (s.diskFull) return '磁盘满了';
  if (s.deadServices > 0) return '${s.deadServices} 个服务停了';
  if (s.jobs.isNotEmpty) return '${s.jobs.length} 个任务在跑';
  if (s.liveServices > 0) return '${s.liveServices} 个服务在跑';
  if (s.outdated && s.reachable) return '下次用到时更新';
  if (s.running) return '空闲';
  return null;
}

/// 重启确认里的说明。
String computerRestartText(ComputerStatus s) => [
      if (s.jobs.isNotEmpty) '会停掉 ${s.jobs.length} 个正在跑的后台任务。',
      if (s.liveServices > 0) '${s.liveServices} 个常驻服务会马上重新拉起。',
      '文件和装过的软件都在，下次用到时自动开机。',
    ].join();

/// 读屏一句话。
String computerSemantics(ComputerStatus s) => '电脑${computerStateLabel(s.state)}，${computerDetail(s)}'
    '${s.jobs.isEmpty ? '' : '，${s.jobs.length} 个后台任务在跑'}'
    '${s.liveServices == 0 ? '' : '，${s.liveServices} 个常驻服务'}${s.deadServices == 0 ? '' : '，${s.deadServices} 个服务停了'}';

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
String processTitle(ComputerProcess p) => commandTitle(p.command);

/// 命令去掉开头程序的路径：“/usr/bin/python3 a.py” → “python3 a.py”。
String commandTitle(String command) {
  final c = command.trim();
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

// ---- v1.94 内存去哪了（服务器 app/memory_view.py；网页版 lib/computer.ts 同一套）----

/// 一行的归属：后台任务 / 常驻服务（整个进程组算一个，点了打开它）/ 不属于任务的程序（对话里直接跑的、nohup 的）。
enum MemoryOwner { job, service, process }

class MemoryRow {
  const MemoryRow({required this.owner, required this.title, required this.memory, this.id, this.pid, this.processes = 1, this.share = 0});
  factory MemoryRow.fromJson(Map<String, dynamic> j) => MemoryRow(
        owner: switch (j['kind']) { 'job' => MemoryOwner.job, 'service' => MemoryOwner.service, _ => MemoryOwner.process },
        title: j['title'] as String? ?? '',
        memory: (j['memory'] as num?)?.toInt() ?? 0,
        id: j['id'] as String?,
        pid: (j['pid'] as num?)?.toInt(),
        processes: (j['processes'] as num?)?.toInt() ?? 1,
        share: ((j['share'] as num?)?.toDouble() ?? 0).clamp(0, 1).toDouble(),
      );
  final MemoryOwner owner;
  final String title;
  final int memory, processes;
  final String? id;
  final int? pid;

  /// 占已用的比例（0–1）。
  final double share;
  String get key => id ?? 'pid-$pid';
}

class MemoryView {
  const MemoryView({required this.used, this.limit, this.rows = const [], this.other = 0});
  factory MemoryView.fromJson(Map<String, dynamic> j) => MemoryView(
        used: (j['used'] as num?)?.toInt() ?? 0,
        limit: (j['limit'] as num?)?.toInt(),
        rows: [
          for (final x in (j['rows'] as List? ?? const []))
            if (x is Map) MemoryRow.fromJson(x.cast<String, dynamic>())
        ],
        other: (j['other'] as num?)?.toInt() ?? 0,
      );
  final int used, other;
  final int? limit;

  /// 从大到小，最多 6 行。
  final List<MemoryRow> rows;

  double? get ratio => limit == null || limit! <= 0 ? null : (used / limit!).clamp(0, 1).toDouble();

  /// 和状态块的内存条同一个门槛。
  bool get tight => (ratio ?? 0) >= computerMemoryTight;

  /// 其它占已用的比例。
  double get otherShare => used <= 0 ? 0 : (other / used).clamp(0, 1).toDouble();
}

/// 这一节要不要出现：电脑在跑、有谁可排（只剩“其它”时状态块那条内存条已经够了）。
MemoryView? memoryViewOf(ComputerStatus s) {
  final m = s.memory;
  return s.running && m != null && m.rows.isNotEmpty ? m : null;
}

/// 头一行：“已用 800 MB，上限 1 GB”。
String memoryViewLine(MemoryView v) => '已用 ${formatSize(v.used)}${v.limit != null ? '，上限 ${formatSize(v.limit!)}' : ''}';

/// 快满时的一句（点名最大的那个）；平时 null。
String? memoryTightNote(MemoryView v) {
  if (!v.tight) return null;
  final top = v.rows.isEmpty ? null : v.rows.first;
  final who = top == null ? '' : '，最大的是「${memoryRowTitle(top)}」（约 ${formatSize(top.memory)}），先停它最管用';
  return '快满了：再涨系统会强制结束程序（先结束普通后台任务）$who';
}

String memoryRowTitle(MemoryRow r) => r.owner == MemoryOwner.process ? commandTitle(r.title) : r.title;

/// 行的副标题：“后台任务 · 3 个进程 · 占 42%”。
String memoryRowLine(MemoryRow r) => [
      switch (r.owner) {
        MemoryOwner.job => '后台任务',
        MemoryOwner.service => '常驻服务',
        MemoryOwner.process => r.pid != null ? '程序 · PID ${r.pid}' : '程序',
      },
      if (r.processes > 1) '${r.processes} 个进程',
      '占 ${memoryPercent(r.share)}',
    ].join(' · ');

String memoryPercent(double share) => share > 0 && share < 0.01 ? '不到 1%' : '${(share * 100).round()}%';

const memoryOtherTitle = '其它';

String memoryOtherLine(MemoryView v) => '系统和零碎小程序 · 占 ${memoryPercent(v.otherShare)}';

/// 读屏一句话。
String memorySemantics(MemoryView v) => [
      memoryViewLine(v),
      ?memoryTightNote(v),
      for (final r in v.rows) '${memoryRowTitle(r)}，${formatSize(r.memory)}，${memoryRowLine(r)}',
      if (v.other > 0) '$memoryOtherTitle ${formatSize(v.other)}',
    ].join('；');

// ---- v1.98 磁盘谁写得最多（服务器 app/job_disk.leaders；网页版 lib/computer.ts 同一套）----

/// 最近 7 天结束的一个后台任务和它结算时的磁盘账。logKept = 完整日志还在（“清理”能腾出日志那份；写的文件是你的，不清）。
class DiskJob {
  const DiskJob({required this.job, required this.disk, this.logKept = false});

  /// 没有可用的磁盘账 → null（不列）。
  static DiskJob? tryParse(Map<String, dynamic> j) {
    final d = JobDisk.tryParse(j['disk']);
    if (d == null || d.written + d.log <= 0) return null;
    return DiskJob(job: JobInfo.fromJson(j), disk: d, logKept: j['log_kept'] == true);
  }

  final JobInfo job;
  final JobDisk disk;
  final bool logKept;

  /// 日志清掉了就只剩写的文件那份还算数。
  int get total => disk.written + (logKept ? disk.log : 0);
}

const diskJobsTitle = '最近 7 天谁写得最多';

/// 这一节的行：去掉已经算不出东西的（日志清了、也没写文件），从大到小。
List<DiskJob> diskJobRows(ComputerStatus s) =>
    [for (final r in s.diskJobs) if (r.total > 0) r]..sort((a, b) => b.total.compareTo(a.total));

/// 占整个工作区已用的比例（0–1）；不知道已用 → 按最大那行算。
double diskJobShare(ComputerStatus s, DiskJob r) {
  final rows = diskJobRows(s);
  final base = s.diskUsed > 0 ? s.diskUsed : (rows.isEmpty ? 0 : rows.first.total);
  return base <= 0 ? 0 : (r.total / base).clamp(0, 1).toDouble();
}

/// 行的副标题：“2 天前 · 主要写在 node_modules/ · 日志 2 MB”。日志清了 → “日志已清”。
String diskJobLine(DiskJob r, {DateTime? now}) => [
      if (r.job.finishedAt != null) formatAgo(r.job.finishedAt, now: now),
      if (r.disk.top.isNotEmpty) '主要写在 ${jobDiskGroupName(r.disk.top.first.path)}' else if (r.disk.written == 0) '只有日志',
      if (r.disk.log > 0) r.logKept ? '日志 ${formatSize(r.disk.log)}' : '日志已清',
      if (r.disk.overlap > 0 && r.disk.written > 0) '含同时段任务',
    ].join(' · ');

/// 行尾的大小（写入有 partial 时带“+”：只数了一部分）。
String diskJobSize(DiskJob r) => '${formatSize(r.total)}${r.disk.partial ? '+' : ''}';

/// 头一句：写的文件是你的，不会被“清理”删；日志能清多少。
String diskJobsNote(ComputerStatus s) {
  final logs = diskJobRows(s).where((r) => r.logKept).fold<int>(0, (a, r) => a + r.disk.log);
  return '按任务结束时数的账；写下的文件不会被清理，要腾地方得删它们${logs > 0 ? '，日志共 ${formatSize(logs)} 可以清' : ''}';
}

String diskJobsSemantics(ComputerStatus s, {DateTime? now}) => [
      diskJobsTitle,
      for (final r in diskJobRows(s)) '${r.job.title}，${diskJobSize(r)}，${diskJobLine(r, now: now)}',
    ].join('；');

/// 整台服务器（v2.85，后端 app/machine.py）：字节；读不到的为 null。
class MachineInfo {
  const MachineInfo({this.cpus, this.load1, this.memoryTotal, this.memoryUsed, this.diskTotal, this.diskUsed});
  factory MachineInfo.fromJson(Map<String, dynamic> j) => MachineInfo(
        cpus: (j['cpus'] as num?)?.toInt(),
        load1: (j['load1'] as num?)?.toDouble(),
        memoryTotal: (j['memory_total'] as num?)?.toInt(),
        memoryUsed: (j['memory_used'] as num?)?.toInt(),
        diskTotal: (j['disk_total'] as num?)?.toInt(),
        diskUsed: (j['disk_used'] as num?)?.toInt(),
      );
  final int? cpus, memoryTotal, memoryUsed, diskTotal, diskUsed;
  final double? load1;
}

/// “整台服务器”一行的副标题：4 核 · 内存 1.2 GB / 3.8 GB · 磁盘 12 GB / 40 GB。全读不到 → null（整行不画）。
String? machineLine(MachineInfo m) {
  final parts = [
    if (m.cpus != null) '${m.cpus} 核${m.load1 != null ? '（负载 ${m.load1!.toStringAsFixed(1)}）' : ''}',
    if (m.memoryTotal != null) '内存 ${m.memoryUsed != null ? '${formatSize(m.memoryUsed!)} / ' : ''}${formatSize(m.memoryTotal!)}',
    if (m.diskTotal != null) '磁盘 ${m.diskUsed != null ? '${formatSize(m.diskUsed!)} / ' : ''}${formatSize(m.diskTotal!)}',
  ];
  return parts.isEmpty ? null : parts.join(' · ');
}

/// 电脑页页头的说明（v2.85，用户 16:03“对不上 VPS 面板”）：先说清这是服务器上隔出来的一块、各有多大，再说用途。
String computerIntro(ComputerStatus? s, {required bool personal}) {
  final size = [
    if (s?.memoryLimit != null) '内存 ${formatSize(s!.memoryLimit!)}',
    if (s?.diskLimit != null) '空间 ${formatSize(s!.diskLimit!)}',
  ].join(' · ');
  final what = personal ? '你的云电脑' : '这个项目的云电脑';
  final head = size.isEmpty ? '$what是服务器上隔出来的一块云端 Linux' : '$what是服务器上隔出来的一块云端 Linux（$size）';
  return personal
      ? '$head：我在这里跑代码、装软件、做后台任务，产物放进“我的文件”。'
      : '$head：项目里的对话都在这里跑代码、装软件、做后台任务，文件就是项目文件。';
}
