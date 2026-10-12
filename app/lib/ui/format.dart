// 展示用的格式化：文件大小、相对时间、钟点、耗时。所有页面共用，措辞统一。
String formatSize(int b) => b < 1024
    ? '$b B'
    : b < 1 << 20
        ? '${(b / 1024).toStringAsFixed(0)} KB'
        : b < 1 << 30
            ? '${(b / (1 << 20)).toStringAsFixed(1)} MB'
            : '${_trim1(b / (1 << 30))} GB';

String _trim1(double v) {
  final s = v.toStringAsFixed(1);
  return s.endsWith('.0') ? s.substring(0, s.length - 2) : s;
}

/// 文件卡第二行的“是什么”——唯一规则（网页 lib/files.ts fileKind 同义）：先看扩展名，再看 mime 大类，都不认识 = 空。
String fileKind(String name, String mime) {
  final ext = name.contains('.') ? name.split('.').last.toLowerCase() : '';
  const byExt = {
    'pdf': 'PDF 文档', 'doc': 'Word 文档', 'docx': 'Word 文档', 'md': '文档', 'txt': '文本',
    'xls': '表格', 'xlsx': '表格', 'csv': '表格', 'ppt': '演示文稿', 'pptx': '演示文稿', 'key': '演示文稿',
    'zip': '压缩包', 'gz': '压缩包', 'tgz': '压缩包', 'tar': '压缩包', '7z': '压缩包', 'rar': '压缩包',
    'html': '网页', 'json': '数据', 'svg': '矢量图',
  };
  final hit = byExt[ext];
  if (hit != null) return hit;
  if (mime.startsWith('image/')) return '图片';
  if (mime.startsWith('audio/')) return '音频';
  if (mime.startsWith('video/')) return '视频';
  if (mime.startsWith('text/')) return '文本';
  return '';
}

/// 文件卡第二行：[种类 · ]大小[ · 我的文件/项目文件]（工作区文件卡才有最后一段：它会跟着工作区里的文件变）。
String fileSubtitle(String name, String mime, int size, {String? workspaceTitle}) =>
    [fileKind(name, mime), formatSize(size), ?workspaceTitle].where((s) => s.isNotEmpty).join(' · ');

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

/// 一个展示值里“唯一的那个数字”（面板关键数字滚动用）：'¥1,280.50 / 月' → 前缀 '¥'、1280.5、两位小数、千分位、后缀 ' / 月'。
/// 只认恰好一个数字的值；'17:42'、'2026-10-11'、'3/5' 这类有好几段数字的、或没有数字的返回 null（照原样显示，不滚动）。
/// 正负号留在前缀里（'+1.2%'、'-3°C'），所以滚动时符号不闪。
class NumberParts {
  const NumberParts(this.prefix, this.value, this.decimals, this.grouped, this.suffix);
  final String prefix, suffix;
  final double value;
  final int decimals;
  final bool grouped;

  static final _num = RegExp(r'\d[\d,]*(?:\.\d+)?');
  static const _maxDigits = 15; // 再长 double 就不精确了，不滚

  static NumberParts? parse(String s) {
    final all = _num.allMatches(s).toList();
    if (all.length != 1) return null;
    final m = all.single;
    final raw = m.group(0)!;
    final grouped = raw.contains(',');
    if (grouped && !RegExp(r'^\d{1,3}(,\d{3})+(\.\d+)?$').hasMatch(raw)) return null; // '1,2,3' 不是千分位
    final plain = raw.replaceAll(',', '');
    if (plain.replaceAll('.', '').length > _maxDigits) return null;
    final dot = plain.indexOf('.');
    return NumberParts(s.substring(0, m.start), double.parse(plain), dot < 0 ? 0 : plain.length - dot - 1, grouped, s.substring(m.end));
  }

  /// 用同样的前后缀、小数位、千分位把 v 写回去（滚动中的每一帧）。
  String format(double v) {
    var n = v.abs().toStringAsFixed(decimals);
    if (grouped) {
      final parts = n.split('.');
      final whole = parts[0].replaceAllMapped(RegExp(r'\B(?=(\d{3})+$)'), (_) => ',');
      n = parts.length > 1 ? '$whole.${parts[1]}' : whole;
    }
    return '$prefix$n$suffix';
  }
}
