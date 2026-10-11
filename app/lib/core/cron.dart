// cron 的人话描述（只用于展示，真正调度在后端）。与网页版 lib/cron.ts 对应。
const _week = ['周日', '周一', '周二', '周三', '周四', '周五', '周六'];

String describeCron(String cron) {
  final f = cron.trim().split(RegExp(r'\s+'));
  if (f.length < 5) return cron;
  final (m, h, dom, dow) = (f[0], f[1], f[2], f[4]);
  final num = RegExp(r'^\d+$');
  if (num.hasMatch(m) && h == '*') return '每小时第 $m 分';
  if (!num.hasMatch(m) || !num.hasMatch(h)) return cron;
  final time = '${h.padLeft(2, '0')}:${m.padLeft(2, '0')}';
  if (dow == '1-5') return '工作日 $time';
  if (RegExp(r'^\d$').hasMatch(dow)) return '每${_week[int.parse(dow) % 7]} $time';
  if (num.hasMatch(dom)) return '每月 $dom 日 $time';
  return '每天 $time';
}

const cronPresets = [
  ('每天 08:00', '0 8 * * *'),
  ('工作日 09:00', '0 9 * * 1-5'),
  ('每周一 10:00', '0 10 * * 1'),
  ('每晚 21:00', '0 21 * * *'),
];

/// 这条 cron 今天（[now] 所在的本地日）会不会跑、几点跑：只认固定“分 时”（每小时这类不算“今天的一件事”）。
/// 与网页版 lib/cron.ts cronTodayAt 同规则。
DateTime? cronTodayAt(String cron, DateTime now) {
  final f = cron.trim().split(RegExp(r'\s+'));
  if (f.length < 5) return null;
  final num = RegExp(r'^\d+$');
  final (m, h, dom, dow) = (f[0], f[1], f[2], f[4]);
  if (!num.hasMatch(m) || !num.hasMatch(h)) return null;
  final wd = now.weekday % 7; // cron：0 = 周日
  if (dow != '*') {
    final ok = dow == '1-5' ? wd >= 1 && wd <= 5 : dow.split(',').any((d) => num.hasMatch(d) && int.parse(d) % 7 == wd);
    if (!ok) return null;
  }
  if (dom != '*' && (!num.hasMatch(dom) || int.parse(dom) != now.day)) return null;
  return DateTime(now.year, now.month, now.day, int.parse(h), int.parse(m));
}
