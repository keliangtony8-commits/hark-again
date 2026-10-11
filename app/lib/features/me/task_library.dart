// 定时任务页的纯逻辑（无 UI，单测直接测）：分组、页头摘要、“下一个”、起步模板。
// 网页版同名逻辑在 frontend/src/features/me/taskLibrary.ts，两边规则和措辞保持一致。
import '../../models/resources.dart';
import '../../ui/format.dart';

/// 分组（各组按下次运行先后；没有下次的排后面，保持服务器顺序）：
/// - attention：上次失败、还在启用（停用的失败任务不打扰）；
/// - running：在跑的普通任务；
/// - panels：在刷新的 Home 面板；
/// - idle：已暂停 / 一次性已完成。
({List<ScheduledTask> attention, List<ScheduledTask> running, List<ScheduledTask> panels, List<ScheduledTask> idle})
    groupTasks(List<ScheduledTask> list) {
  final idx = {for (var i = 0; i < list.length; i++) list[i].id: i};
  int byNext(ScheduledTask a, ScheduledTask b) {
    final x = a.nextRunAt, y = b.nextRunAt;
    if (x != null && y != null && x != y) return x.compareTo(y);
    if (x != null && y == null) return -1;
    if (x == null && y != null) return 1;
    return idx[a.id]!.compareTo(idx[b.id]!);
  }

  bool idle(ScheduledTask t) => !t.active || t.done;
  List<ScheduledTask> pick(bool Function(ScheduledTask) f) => [for (final t in list) if (f(t)) t]..sort(byNext);
  return (
    attention: pick((t) => !idle(t) && t.lastFailed && !t.runRequested),
    running: pick((t) => !idle(t) && !(t.lastFailed && !t.runRequested) && !t.isPanel),
    panels: pick((t) => !idle(t) && !(t.lastFailed && !t.runRequested) && t.isPanel),
    idle: [for (final t in list) if (idle(t)) t],
  );
}

/// 页头小标签：“6 个任务 · 4 个在跑 · 1 个上次失败”；空列表是一句引导。
String taskSummary(List<ScheduledTask> list) {
  if (list.isEmpty) return '到点我自己去做的事';
  final g = groupTasks(list);
  final live = list.length - g.idle.length;
  return [
    '${list.length} 个任务',
    live == list.length ? '全部在跑' : '$live 个在跑',
    if (g.attention.isNotEmpty) '${g.attention.length} 个上次失败',
  ].join(' · ');
}

/// 下一个要跑的（启用、未完成、有下次运行时刻里最早的）：(名称, “明天 08:00”)；没有 = null。
(String, String)? nextUp(List<ScheduledTask> list, {DateTime? now}) {
  ScheduledTask? best;
  for (final t in list) {
    if (!t.active || t.done || t.nextRunAt == null) continue;
    if (best == null || t.nextRunAt!.isBefore(best.nextRunAt!)) best = t;
  }
  if (best == null) return null;
  final n = now ?? DateTime.now();
  final soon = best.nextRunAt!.difference(n).inSeconds < 60;
  return (best.name, soon ? '马上' : formatWhen(best.nextRunAt!, now: n));
}

/// 起步模板：空列表里给几颗，点一下带着内容打开新建表单（还没保存，改完再建）。
class TaskStarter {
  const TaskStarter(this.name, this.prompt, this.cron);
  final String name, prompt, cron;
}

const taskStarters = [
  TaskStarter('今日简报', '帮我准备今天：天气、日程、待办和需要注意的事，简短一点。', '0 8 * * *'),
  TaskStarter('每周复盘', '回顾这周的对话和完成的事，按“完成 / 没做完 / 下周重点”写一段复盘。', '0 21 * * 0'),
  TaskStarter('睡前背单词', '给我 10 个考研英语高频词，带例句，最后出 3 道小测。', '0 22 * * *'),
];
