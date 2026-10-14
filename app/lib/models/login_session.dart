// 登录设备（v2.61，对标 Hark 设置 → 安全）：服务器 /api/auth/sessions 的数据和“安全”页用到的文字规则。
// 哪个 token 还算数只在后端 app/login_sessions.py；这里只解析 + 决定怎么说（纯函数，test/login_session_test.dart 覆盖）。
import '../ui/format.dart';

class LoginSession {
  const LoginSession({required this.id, required this.label, required this.kind, this.createdAt, this.lastSeenAt, this.current = false});
  final String id, label, kind; // kind: app | browser | other
  final DateTime? createdAt, lastSeenAt;
  final bool current;

  factory LoginSession.fromJson(Map<String, dynamic> j) => LoginSession(
        id: '${j['id'] ?? ''}',
        label: '${j['label'] ?? '未知设备'}',
        kind: '${j['kind'] ?? 'other'}',
        createdAt: j['created_at'] is String ? DateTime.tryParse(j['created_at'] as String)?.toLocal() : null,
        lastSeenAt: j['last_seen_at'] is String ? DateTime.tryParse(j['last_seen_at'] as String)?.toLocal() : null,
        current: j['current'] == true,
      );
}

List<LoginSession> parseLoginSessions(dynamic j) =>
    [for (final s in (j is Map ? j['sessions'] as List? ?? const [] : const [])) LoginSession.fromJson(Map<String, dynamic>.from(s as Map))];

/// 登录时报给服务器的设备名（列表里就显示它）：按系统给“Android App”这类；后端认“app”字样归成 App 一类。
String appDeviceLabel(String os) => switch (os) {
      'android' => 'Android App',
      'ios' => 'iPhone App',
      'macos' => 'Mac App',
      'windows' => 'Windows App',
      'linux' => 'Linux App',
      _ => 'App',
    };

/// 副标题：本机写“这台设备”，别的写最近活动；都带登录日期。
String loginSessionLine(LoginSession s, {DateTime? now}) {
  final head = s.current ? '这台设备' : (s.lastSeenAt == null ? '' : '${formatAgo(s.lastSeenAt, now: now)}活动');
  final since = s.createdAt == null ? '' : '${_day(s.createdAt!, now ?? DateTime.now())}登录';
  return [head, since].where((x) => x.isNotEmpty).join(' · ');
}

String _day(DateTime t, DateTime now) {
  final l = t.toLocal(), n = now.toLocal();
  final diff = DateTime(n.year, n.month, n.day).difference(DateTime(l.year, l.month, l.day)).inDays;
  if (diff == 0) return '今天';
  if (diff == 1) return '昨天';
  return l.year == n.year ? '${l.month}月${l.day}日' : '${l.year}年${l.month}月${l.day}日';
}

/// 区块页头：几台设备登着。
String loginSessionsSummary(List<LoginSession> list) => list.length <= 1 ? '只有这台设备登着' : '${list.length} 台设备登着';

/// “退出其他所有设备”后的提示。
String signedOutToast(int n) => n <= 0 ? '没有别的设备登着' : '已退出其他 $n 台设备';

/// 打开两步验证顺手退出了别的设备：恢复码弹层里写一句（0 台不提）。
String? enabledSignedOutToast(int n) => n <= 0 ? null : '为了安全，已退出其他 $n 台设备';
