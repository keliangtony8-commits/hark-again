// 版本（v2.86，home-redesign §K）：客户端版本来自 lib/brand.dart（brand/sync.py 由 VERSION 生成），
// 服务器版本来自 GET /api/version。这里只放纯规则：比大小、关于页那一行怎么写。
import '../brand.dart';

class ServerVersion {
  const ServerVersion({required this.version, required this.minClient});
  final String version;
  final String minClient;

  /// 老服务器没有这个接口 / 字段不对 → null（关于页只显示本机版本）。
  static ServerVersion? fromJson(Object? j) {
    if (j is! Map) return null;
    final v = j['version'], m = j['min_client'];
    if (v is! String || parseVersion(v) == null) return null;
    return ServerVersion(version: v, minClient: m is String && parseVersion(m) != null ? m : '0.0.0');
  }
}

/// "2.86.0" → [2, 86, 0]；不是 X.Y.Z 返回 null。
List<int>? parseVersion(String s) {
  final m = RegExp(r'^(\d+)\.(\d+)\.(\d+)$').firstMatch(s.trim());
  return m == null ? null : [for (var i = 1; i <= 3; i++) int.parse(m.group(i)!)];
}

/// a < b（按 大版本.功能轮.修复）；解析不了的当作不小于（不误报“请更新”）。
bool versionBelow(String a, String b) {
  final x = parseVersion(a), y = parseVersion(b);
  if (x == null || y == null) return false;
  for (var i = 0; i < 3; i++) {
    if (x[i] != y[i]) return x[i] < y[i];
  }
  return false;
}

/// 服务器要求的最低客户端比本机新 = 协议不兼容，要更新 App。
bool clientOutdated(ServerVersion? s, {String client = appVersion}) => s != null && versionBelow(client, s.minClient);

/// 关于页“版本”行的值：本机版本；协议不兼容时后面写“请更新”。服务器版本是下面单独一行（两边不一致一眼看出）。
String clientVersionLabel(ServerVersion? s, {String client = appVersion}) =>
    clientOutdated(s, client: client) ? '$client · 请更新' : client;
