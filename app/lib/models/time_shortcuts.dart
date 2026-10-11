// 常用的“稍后某个时刻”：一次性任务的计划（features/me/schedule_picker.dart）和
// Home 卡片的稍后提醒（features/home/card_snooze.dart）共用这一张表。网页版 lib/timeShortcuts.ts 同规则。

/// 一次性的快捷时刻：1 小时后（取整到 5 分）/ 今晚 20:00（已过就不给）/ 明早 08:00 / 明晚 20:00。
List<(String, DateTime)> onceShortcuts(DateTime now) {
  final inHour = now.add(const Duration(hours: 1));
  final tonight = DateTime(now.year, now.month, now.day, 20);
  final tomorrow = DateTime(now.year, now.month, now.day + 1);
  return [
    ('1 小时后', DateTime(inHour.year, inHour.month, inHour.day, inHour.hour, (inHour.minute ~/ 5 + 1) * 5)),
    if (tonight.isAfter(now.add(const Duration(minutes: 10)))) ('今晚 20:00', tonight),
    ('明早 08:00', tomorrow.add(const Duration(hours: 8))),
    ('明晚 20:00', tomorrow.add(const Duration(hours: 20))),
  ];
}
