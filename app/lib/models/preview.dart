// 端口预览（后端 app/preview.py）：工作区电脑里跑着的网页服务的签名链接，带期限。
// 聊天里的预览卡（PreviewBlock）和电脑页“正在监听的端口”共用这里的文案规则；网页版 lib/preview.ts 同一套。

/// 在监听的一个端口（GET …/computer 的 ports）。loopback = 只监听 127.0.0.1，外面（预览）连不到。
class ListeningPort {
  const ListeningPort({required this.port, this.loopback = false, this.command = ''});
  factory ListeningPort.fromJson(Map<String, dynamic> j) => ListeningPort(
        port: (j['port'] as num?)?.toInt() ?? 0,
        loopback: j['loopback'] == true,
        command: j['command'] as String? ?? '',
      );
  final int port;
  final bool loopback;
  final String command;
}

String portTitle(int port, [String? title]) => (title != null && title.trim().isNotEmpty) ? title.trim() : '端口 $port';

/// 端口行 / 卡片小字：程序名（命令行太长只留前面），只监听本机的写明为什么打不开。
String portLine(ListeningPort p) {
  if (p.loopback) return '只监听本机，预览打不开（要让服务监听 0.0.0.0）';
  return p.command.isEmpty ? '网页服务' : shortCommand(p.command);
}

String shortCommand(String c) {
  final s = c.trim().replaceAll(RegExp(r'\s+'), ' ');
  return s.length <= 48 ? s : '${s.substring(0, 47)}…';
}

/// 有效期一句：“24 小时内有效”“还能用 40 分钟”“已过期”。expires 为空（老卡）→ 空串。
String previewExpiry(DateTime? expires, DateTime now) {
  if (expires == null) return '';
  final left = expires.difference(now);
  if (left <= Duration.zero) return '已过期';
  if (left.inHours >= 1) return '${left.inHours >= 23 ? 24 : left.inHours + 1} 小时内有效';
  return '还能用 ${left.inMinutes < 1 ? 1 : left.inMinutes} 分钟';
}

bool previewExpired(DateTime? expires, DateTime now) => expires != null && !expires.isAfter(now);
