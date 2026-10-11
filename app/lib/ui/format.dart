// 展示用的格式化：文件大小、相对时间、钟点、耗时。所有页面共用，措辞统一。
String formatSize(int b) => b < 1024 ? '$b B' : b < 1 << 20 ? '${(b / 1024).toStringAsFixed(0)} KB' : '${(b / (1 << 20)).toStringAsFixed(1)} MB';

String formatAgo(DateTime? t, {DateTime? now}) {
  if (t == null) return '';
  final d = (now ?? DateTime.now()).difference(t);
  if (d.inMinutes < 1) return '刚刚';
  if (d.inHours < 1) return '${d.inMinutes} 分钟前';
  if (d.inDays < 1) return '${d.inHours} 小时前';
  if (d.inDays < 30) return '${d.inDays} 天前';
  return '${t.year}-${t.month.toString().padLeft(2, '0')}-${t.day.toString().padLeft(2, '0')}';
}

/// 金额：小额多留一位，免得满屏 0.00。CNY 用 ¥，其他直接写币种。
String formatMoney(double v, String currency) {
  final sign = switch (currency) { 'CNY' => '¥', 'USD' => r'$', _ => '$currency ' };
  final digits = v != 0 && v.abs() < 0.1 ? 3 : 2;
  return '$sign${v.toStringAsFixed(digits)}';
}

/// token 数：1234 → 1.2K，2500000 → 2.5M。
String formatTokens(int n) {
  if (n < 1000) return '$n';
  if (n < 1000000) return '${(n / 1000).toStringAsFixed(n < 10000 ? 1 : 0)}K';
  return '${(n / 1000000).toStringAsFixed(n < 10000000 ? 1 : 0)}M';
}

String _two(int n) => n.toString().padLeft(2, '0');

/// 具体时刻：今天 08:00 / 昨天 08:00 / 明天 08:00 / 10月9日 08:00 / 2025年10月9日 08:00（本地时区）。
String formatWhen(DateTime? t, {DateTime? now}) {
  if (t == null) return '';
  final l = t.toLocal(), n = (now ?? DateTime.now()).toLocal();
  final clock = '${_two(l.hour)}:${_two(l.minute)}';
  final day = DateTime(l.year, l.month, l.day), today = DateTime(n.year, n.month, n.day);
  final diff = today.difference(day).inDays;
  if (diff == 0) return '今天 $clock';
  if (diff == 1) return '昨天 $clock';
  if (diff == -1) return '明天 $clock';
  if (l.year == n.year) return '${l.month}月${l.day}日 $clock';
  return '${l.year}年${l.month}月${l.day}日 $clock';
}

/// 耗时：<1 秒 / 12 秒 / 3 分 5 秒 / 1 小时 2 分。
String formatDuration(int ms) {
  if (ms < 1000) return '不到 1 秒';
  final s = ms ~/ 1000;
  if (s < 60) return '$s 秒';
  if (s < 3600) return s % 60 == 0 ? '${s ~/ 60} 分' : '${s ~/ 60} 分 ${s % 60} 秒';
  return '${s ~/ 3600} 小时 ${(s % 3600) ~/ 60} 分';
}

const _weekdays = ['一', '二', '三', '四', '五', '六', '日'];

/// 日期：10月11日 星期日（主页问候、聊天日期分隔共用）。
String formatDate(DateTime t) => '${t.month}月${t.day}日 星期${_weekdays[t.weekday - 1]}';

/// 聊天里的日期分隔：今天 / 昨天 / 10月9日 星期五 / 2025年10月9日 星期四（本地时区）。
String formatDay(DateTime t, {DateTime? now}) {
  final l = t.toLocal(), n = (now ?? DateTime.now()).toLocal();
  final diff = DateTime(n.year, n.month, n.day).difference(DateTime(l.year, l.month, l.day)).inDays;
  if (diff == 0) return '今天';
  if (diff == 1) return '昨天';
  return l.year == n.year ? formatDate(l) : '${l.year}年${formatDate(l)}';
}
