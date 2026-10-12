// 活动时间线（v1.28）：一条回复里助手每次用工具 = 一步（服务器 app/activity.py 定义形状，随消息落库）。
// 生成中由 WS tool.status 的 step 实时更新；完成后在回复上方收成一行“用了 4 步 · 12 秒 ›”，点开逐步回看。
// 这里只放纯规则（文案、计时、读屏），界面在 features/chat/activity_view.dart；网页版同款 lib/activity.ts。

enum ActivityState { running, done, error, denied, stopped }

class ActivityStep {
  const ActivityStep({required this.id, required this.title, this.tool = '', this.detail = '', this.state = ActivityState.running, this.at, this.ms, this.note = ''});

  factory ActivityStep.fromJson(Map<String, dynamic> j) => ActivityStep(
        id: j['id'] as String? ?? '',
        tool: j['tool'] as String? ?? '',
        title: j['title'] as String? ?? '',
        detail: j['detail'] as String? ?? '',
        state: ActivityState.values.asNameMap()[j['state']] ?? ActivityState.done,
        at: DateTime.tryParse(j['at'] as String? ?? '')?.toLocal(),
        ms: (j['ms'] as num?)?.toInt(),
        note: j['note'] as String? ?? '',
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

  bool get running => state == ActivityState.running;

  /// 没成：出错、没批准/没填、被停掉。
  bool get failed => state == ActivityState.error || state == ActivityState.denied || state == ActivityState.stopped;
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
      if (s.ms != null && !s.running) '用时 ${stepDuration(s.ms!)}',
    ].join('，');
