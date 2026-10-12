// 云浏览器里保存的登录（后端 app/browser_sessions.py，接口 GET /api/browser/sessions、DELETE /api/browser/sessions/{name}）。
// 会话按网站起名：在某个网站登录一次，之后的任务都接着用。纯规则——行标题、说明、读屏句子、退出确认文案；网页版 lib/browserSessions.ts 同一套。
import '../ui/format.dart';

class BrowserSession {
  const BrowserSession(
      {required this.name,
      required this.label,
      this.open = false,
      this.saved = false,
      this.lastUsed,
      this.cookies = 0,
      this.domains = const [],
      this.signedInAt,
      this.expiredAt});

  factory BrowserSession.fromJson(Map<String, dynamic> j) => BrowserSession(
        name: j['name'] as String,
        label: j['label'] as String? ?? j['name'] as String,
        open: j['open'] == true,
        saved: j['saved'] == true,
        lastUsed: DateTime.tryParse(j['last_used'] as String? ?? '')?.toLocal(),
        cookies: (j['cookies'] as num?)?.toInt() ?? 0,
        domains: [for (final d in (j['domains'] as List? ?? const [])) d as String],
        signedInAt: DateTime.tryParse(j['signed_in_at'] as String? ?? '')?.toLocal(),
        expiredAt: DateTime.tryParse(j['expired_at'] as String? ?? '')?.toLocal(),
      );

  final String name, label;
  final bool open, saved;
  final DateTime? lastUsed;
  final int cookies;
  final List<String> domains;

  /// 服务端判定的登录状态（v1.36）：登录成功的时刻；之前登录过、后来网站又要登录的时刻（再登录成功会清掉）。
  final DateTime? signedInAt, expiredAt;
  bool get expired => expiredAt != null;
}

/// 最近用过的在前（服务端已排好；这里再保证一次，没时间的放最后，稳定）。
List<BrowserSession> sortBrowserSessions(List<BrowserSession> list) {
  final out = [...list];
  final at = {for (var i = 0; i < out.length; i++) out[i]: i};
  out.sort((a, b) {
    final x = a.lastUsed, y = b.lastUsed;
    if (x == null || y == null) return x == y ? at[a]!.compareTo(at[b]!) : (x == null ? 1 : -1);
    final c = y.compareTo(x);
    return c != 0 ? c : at[a]!.compareTo(at[b]!);
  });
  return out;
}

/// 行尾的状态字：登录过期 → 已过期（警示色）；开着 → 正在用；否则不给（时间在说明行里）。
String? browserSessionHint(BrowserSession s) => s.expired ? '已过期' : (s.open ? '正在用' : null);

/// 说明行：上次用的时间 + 登录状态（过期 → 下次用到时会请你重新登录）。
String browserSessionDetail(BrowserSession s, {DateTime? now}) {
  final when = s.lastUsed == null ? null : '上次用 ${formatAgo(s.lastUsed, now: now)}';
  final kept = s.expired
      ? browserSessionExpiredLine
      : (s.saved && s.cookies > 0 ? '登录已保存' : '还没有保存的登录');
  return [?when, kept].join(' · ');
}

const browserSessionExpiredLine = '登录过期了，用到时会请你重新登录';

String browserSessionSemantics(BrowserSession s, {DateTime? now}) =>
    '${s.label}，${browserSessionDetail(s, now: now)}${!s.expired && s.open ? '，正在用' : ''}';

String browserSignOutText(BrowserSession s) => '会关掉这个网站的浏览器，并删掉保存的登录。下次要用 ${s.label} 时需要重新登录。';

const browserSessionsEmpty = '还没有保存的网站登录';
const browserSessionsEmptyLine = '让我在网页上登录一次，之后的任务都会接着用这个登录。';
