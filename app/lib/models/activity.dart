// 活动时间线（v1.28）：一条回复里助手每次用工具 = 一步（服务器 app/activity.py 定义形状，随消息落库）。
// 生成中由 WS tool.status 的 step 实时更新；完成后在回复上方收成一行“用了 4 步 · 12 秒 ›”，点开逐步回看。
// 这里只放纯规则（文案、计时、读屏），界面在 features/chat/activity_view.dart；网页版同款 lib/activity.ts。

enum ActivityState { running, done, error, denied, stopped }

/// 这一步改了工作区里的文件（v1.34：write_file / edit_file）：服务器 app/file_edit.py 的 change。
/// diff = unified diff 去掉文件头（@@ 段头、+ 新增、- 删除、空格开头是上下文）；hidden = 像密钥的文件，不给 diff。
class FileChange {
  const FileChange({required this.path, this.added = 0, this.removed = 0, this.diff = '', this.created = false, this.hidden = false, this.big = false, this.deleted = false, this.movedFrom = ''});

  static FileChange? fromJson(Object? raw) {
    if (raw is! Map<String, dynamic>) return null;
    return FileChange(
      path: raw['path'] as String? ?? '',
      added: (raw['added'] as num?)?.toInt() ?? 0,
      removed: (raw['removed'] as num?)?.toInt() ?? 0,
      diff: raw['diff'] as String? ?? '',
      created: raw['created'] == true,
      hidden: raw['hidden'] == true,
      big: raw['big'] == true,
      deleted: raw['deleted'] == true,
      movedFrom: raw['moved_from'] as String? ?? '',
    );
  }

  final String path, diff;
  final int added, removed;
  final bool created, hidden;

  /// 改动卡（v1.68）：big = 太大没记基线（不能撤销）；deleted = 这一轮之后文件已经不在了。
  final bool big, deleted;

  /// v1.69 apply_patch 改名：从哪个路径改过来（diff 按原文件算）。
  final String movedFrom;

  /// 行里显示的路径：改名的写成 “旧 → 新”。
  String get label => movedFrom.isEmpty ? path : '$movedFrom → $path';

  /// 有 diff 可展开看。
  bool get expandable => diff.isNotEmpty;

  /// 读屏：“新建，增加 3 行” / “增加 2 行，删除 1 行”。
  String get semantics => [
        if (created) '新建',
        if (movedFrom.isNotEmpty) '从 $movedFrom 改名',
        '增加 $added 行',
        if (removed > 0) '删除 $removed 行',
      ].join('，');
}

enum DiffKind { hunk, add, remove, context, note }

/// diff 文本拆成行，标出类型（界面按类型上色）。
List<(DiffKind, String)> diffLines(String diff) => [
      for (final l in diff.split('\n'))
        if (l.startsWith('@@'))
          (DiffKind.hunk, l)
        else if (l.startsWith('+'))
          (DiffKind.add, l)
        else if (l.startsWith('-'))
          (DiffKind.remove, l)
        else if (l.startsWith('…'))
          (DiffKind.note, l)
        else
          (DiffKind.context, l),
    ];

class ActivityStep {
  const ActivityStep({required this.id, required this.title, this.tool = '', this.detail = '', this.state = ActivityState.running, this.at, this.ms, this.note = '', this.files = const []});

  factory ActivityStep.fromJson(Map<String, dynamic> j) => ActivityStep(
        id: j['id'] as String? ?? '',
        tool: j['tool'] as String? ?? '',
        title: j['title'] as String? ?? '',
        detail: j['detail'] as String? ?? '',
        state: ActivityState.values.asNameMap()[j['state']] ?? ActivityState.done,
        at: DateTime.tryParse(j['at'] as String? ?? '')?.toLocal(),
        ms: (j['ms'] as num?)?.toInt(),
        note: j['note'] as String? ?? '',
        files: changedFiles(j),
      );

  /// WS tool.status：新服务器带完整 step；老服务器只有 label / state，退化成只有标题的一步。
  factory ActivityStep.fromStatus(Map<String, dynamic> e) {
    if (e['step'] case final Map<String, dynamic> s when s.isNotEmpty) return ActivityStep.fromJson(s);
    final label = e['label'] as String? ?? '';
    return ActivityStep(
      id: e['id'] as String? ?? '',
      tool: e['name'] as String? ?? '',
      title: label.startsWith('正在') ? label.substring(2) : label,
      state: ActivityState.values.asNameMap()[e['state']] ?? ActivityState.done,
    );
  }

  final String id, tool, title, detail, note;
  final ActivityState state;
  final DateTime? at;
  final int? ms;
  /// 这一步改了的文件：write_file / edit_file 一个（step.change），apply_patch 可能几个（step.changes，v1.69）。
  final List<FileChange> files;

  /// 行尾 “+N −M”：一个文件就是它本身；几个文件合计（路径为空，没有 diff）。
  FileChange? get change => switch (files) {
        [] => null,
        [final one] => one,
        _ => FileChange(
            path: '',
            added: files.fold(0, (n, f) => n + f.added),
            removed: files.fold(0, (n, f) => n + f.removed),
          ),
      };

  /// 有东西可展开：一个文件看 diff，几个文件看逐个文件。
  bool get expandable => files.length > 1 || (files.isNotEmpty && files.first.expandable);

  bool get running => state == ActivityState.running;

  /// 没成：出错、没批准/没填、被停掉。
  bool get failed => state == ActivityState.error || state == ActivityState.denied || state == ActivityState.stopped;
}

/// 时间线一步里逐个文件的状态字：这一步删掉的文件没有 diff 可看，写“已删除”（行数在读屏里）。
String? stepFileTag(FileChange f) => f.deleted ? '已删除' : null;

/// step 里的改动：changes 列表优先，否则单个 change。
List<FileChange> changedFiles(Map<String, dynamic> j) {
  if (j['changes'] case final List list) return [for (final x in list) ?FileChange.fromJson(x)];
  return [?FileChange.fromJson(j['change'])];
}

/// 生成中把一步合进列表：同 id 原地换，新的接在后面。
List<ActivityStep> mergeStep(List<ActivityStep> steps, ActivityStep s) {
  final i = steps.indexWhere((x) => x.id == s.id);
  return i < 0 ? [...steps, s] : [for (final x in steps) x.id == s.id ? s : x];
}

List<ActivityStep> stepsFrom(Object? raw) => [
      for (final x in (raw as List? ?? const []))
        if (x is Map<String, dynamic>) ActivityStep.fromJson(x),
    ];

/// “0.4 秒” / “12 秒” / “1 分 5 秒”。
String stepDuration(int ms) {
  if (ms < 1000) return '${(ms / 1000).toStringAsFixed(1)} 秒';
  final s = (ms / 1000).round();
  return s < 60 ? '$s 秒' : '${s ~/ 60} 分 ${s % 60} 秒';
}

/// 整段用时 = 第一步开始到最后一步结束（工具之间模型思考的时间也算进去，和用户感受到的一致）。
/// 有一步没带时间（老服务器）→ null。
int? activitySpanMs(List<ActivityStep> steps) {
  final starts = [for (final s in steps) s.at];
  if (steps.isEmpty || starts.any((t) => t == null)) return null;
  final first = starts.whereType<DateTime>().reduce((a, b) => a.isBefore(b) ? a : b);
  var end = first;
  for (final s in steps) {
    final e = s.at!.add(Duration(milliseconds: s.ms ?? 0));
    if (e.isAfter(end)) end = e;
  }
  return end.difference(first).inMilliseconds;
}

int failedSteps(List<ActivityStep> steps) => steps.where((s) => s.failed).length;

/// 回复上方那一行：“用了 4 步 · 12 秒”；生成中 “已用 2 步”。
String activitySummary(List<ActivityStep> steps, {bool pending = false}) {
  final n = steps.length;
  if (pending) return '已用 $n 步';
  final span = activitySpanMs(steps);
  return span == null ? '用了 $n 步' : '用了 $n 步 · ${stepDuration(span)}';
}

/// 一步的状态字（读屏、没成时行尾的原因前缀）。
String stepStateLabel(ActivityState s) => switch (s) {
      ActivityState.running => '进行中',
      ActivityState.done => '完成',
      ActivityState.error => '没成功',
      ActivityState.denied => '没执行',
      ActivityState.stopped => '被停止',
    };

/// 一步的读屏文案：“运行命令 ls -la，完成，用时 0.4 秒”。
String stepSemantics(ActivityStep s) => [
      [s.title, if (s.detail.isNotEmpty) s.detail].join(' '),
      stepStateLabel(s.state),
      if (s.note.isNotEmpty) s.note,
      if (s.files.length > 1) '改了 ${s.files.length} 个文件，${s.change!.semantics}' else if (s.change case final c?) c.semantics,
      if (s.ms != null && !s.running) '用时 ${stepDuration(s.ms!)}',
    ].join('，');
