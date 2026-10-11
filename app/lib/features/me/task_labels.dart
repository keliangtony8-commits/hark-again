// 定时任务的状态文案：列表行和详情页共用，措辞只在这里定（网页版 lib/taskLabels.ts 同规则）。
import 'package:flutter/material.dart' show IconData, Icons;

import '../../core/cron.dart';
import '../../models/resources.dart';
import '../../ui/format.dart';

/// 计划本身：每天 08:00 / 工作日 09:00 / 一次 · 明天 08:00。
String scheduleLabel(ScheduledTask t, {DateTime? now}) =>
    t.isOnce ? '一次 · ${formatWhen(t.runAt, now: now)}' : describeCron(t.cron);

/// 下次运行：已完成（一次性跑过）/ 连续失败已暂停 / 已暂停 / 马上运行（过期补跑或一分钟内）/ 下次 明天 08:00；cron 无效时为空。
/// 一次性任务的“下次”就是计划时刻，scheduleLabel 已经写了，这里不再重复。
String nextRunLabel(ScheduledTask t, {DateTime? now}) {
  if (t.done) return '已完成';
  if (t.autoPaused) return '连续失败，已暂停';
  if (!t.active) return '已暂停';
  final at = t.nextRunAt;
  if (at == null) return '';
  final n = now ?? DateTime.now();
  if (at.difference(n).inSeconds < 60) return '马上运行';
  if (t.isOnce) return '';
  return '下次 ${formatWhen(at, now: n)}';
}

/// 列表行的状态：排队 > 自动暂停 > 连续失败 N 次 / 上次失败 > 下次运行。
String taskStateLabel(ScheduledTask t, {DateTime? now}) {
  if (t.runRequested) return '即将运行…';
  if (t.autoPaused) return '连续失败 ${t.failStreak} 次，已暂停';
  if (t.lastFailed) return t.failStreak > 1 ? '连续失败 ${t.failStreak} 次' : '上次失败';
  return nextRunLabel(t, now: now);
}

/// 详情页的提示条：只有被自动暂停时才有，告诉用户怎么恢复。
String? autoPauseNote(ScheduledTask t) => t.autoPaused
    ? '连着失败了 ${t.failStreak} 次，我先把它停了，免得一直白跑。改好后打开开关恢复；也可以先“立即运行”试一次，成功了会自动恢复。'
    : null;

/// 行首/详情图标：面板 / 一次性（闹钟）/ 重复（时钟）。
IconData taskIcon(ScheduledTask t) =>
    t.isPanel ? Icons.dashboard_outlined : (t.isOnce ? Icons.alarm_rounded : Icons.schedule_rounded);
