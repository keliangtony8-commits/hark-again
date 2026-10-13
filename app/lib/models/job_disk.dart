// v1.96 后台任务的磁盘账（后端 app/job_disk.py）：日志 + 运行期间工作区里新写或改过的文件（按顶层条目分组）。
// 运行中由 /api/jobs/{id} 现数（服务器缓存 30 秒），结束了是结算时存下的账（之后删文件也不变）。
// 网页版 frontend/src/lib/jobs.ts 同一套规则。
import '../ui/format.dart';

class JobDiskGroup {
  const JobDiskGroup(this.path, this.size);
  final String path;
  final int size;
}

class JobDisk {
  const JobDisk({required this.log, required this.written, required this.files, this.top = const [], this.overlap = 0, this.partial = false});

  /// 字段缺 / 类型不对 / 负数 → null（宁可不显示也不显示错的）。
  static JobDisk? tryParse(Object? raw) {
    if (raw is! Map) return null;
    final log = raw['log'], written = raw['written'], files = raw['files'], overlap = raw['overlap'] ?? 0;
    if (log is! num || written is! num || files is! num || overlap is! num) return null;
    if (log < 0 || written < 0 || files < 0 || overlap < 0) return null;
    final top = <JobDiskGroup>[
      for (final t in (raw['top'] is List ? raw['top'] as List : const []))
        if (t is Map && t['path'] is String && (t['path'] as String).isNotEmpty && t['size'] is num && (t['size'] as num) > 0)
          JobDiskGroup(t['path'] as String, (t['size'] as num).toInt()),
    ];
    return JobDisk(log: log.toInt(), written: written.toInt(), files: files.toInt(), top: top.take(3).toList(),
        overlap: overlap.toInt(), partial: raw['partial'] == true);
  }

  final int log, written, files, overlap;
  final List<JobDiskGroup> top;
  final bool partial;
}

/// 日志到这么大，即使没写文件卡片也提一句（同后端 job_disk.NOTE_MIN 的量级）。
const jobDiskLogShown = 1 << 20;

/// 卡片上要不要画磁盘那行：写了文件，或日志够大。
bool jobDiskShown(JobDisk? d) => d != null && (d.files > 0 || d.log >= jobDiskLogShown);

/// .home/ = 沙盒家目录（pip / npm -g 装的软件）。
String jobDiskGroupName(String path) => path == '.home/' ? '装的软件' : path;

/// 卡片那行：写入 2.0 MB · 12 个文件 · 最多 images/ · 日志 300 KB（· 含同时段任务）。
String jobDiskLabel(JobDisk d) => [
      if (d.files > 0) ...[
        '写入 ${formatSize(d.written)}${d.partial ? '+' : ''}',
        '${d.files}${d.partial ? '+' : ''} 个文件',
        if (d.top.isNotEmpty) '最多 ${jobDiskGroupName(d.top.first.path)}',
      ] else
        '没写新文件',
      '日志 ${formatSize(d.log)}',
      if (d.overlap > 0 && d.files > 0) '含同时段任务',
    ].join(' · ');

/// 完整日志页里的明细：每组一段（images/ 2.0 MB、装的软件 8.0 MB），再说清口径。
String jobDiskDetail(JobDisk d) {
  final groups = d.top.map((t) => '${jobDiskGroupName(t.path)} ${formatSize(t.size)}').join('、');
  final notes = [
    if (d.partial) '文件太多只数了一部分',
    if (d.overlap > 0) '同时段还有 ${d.overlap} 个任务在跑，可能含它们写的',
  ];
  final head = d.files > 0 ? '运行期间新写或改过 ${d.files} 个文件，共 ${formatSize(d.written)}${groups.isEmpty ? '' : '：$groups'}' : '运行期间没有新写文件';
  return '$head；日志 ${formatSize(d.log)}${notes.isEmpty ? '' : '（${notes.join('；')}）'}';
}

/// 读屏。
String jobDiskSemantics(JobDisk d) =>
    d.files > 0 ? '写入 ${formatSize(d.written)}，${d.files} 个文件，日志 ${formatSize(d.log)}' : '没写新文件，日志 ${formatSize(d.log)}';
