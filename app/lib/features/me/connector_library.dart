// 连接器页与保险箱页的纯逻辑（不碰界面，便于测试）：排序、页头摘要、保险箱分组。
// 网页版 frontend/src/features/me/connectorLibrary.ts 与此同规则。
import '../../models/resources.dart';

/// 账户排序：已连接的在前，其次是服务器配好、点了就能连的，最后是还没配置的（变淡）。同组保持服务器顺序。
List<Connector> sortAccounts(List<Connector> list) {
  int rank(Connector c) => c.connected ? 0 : (c.configured ? 1 : 2);
  final indexed = list.indexed.toList()..sort((a, b) => rank(a.$2) != rank(b.$2) ? rank(a.$2) - rank(b.$2) : a.$1 - b.$1);
  return [for (final (_, c) in indexed) c];
}

/// MCP 服务器排序：有问题（连不上 / 令牌被拒）的排最前——要你处理的先看到；其余保持添加顺序。
List<McpServerItem> sortServers(List<McpServerItem> list) {
  int rank(McpServerItem s) => s.problemText == null ? 1 : 0;
  final indexed = list.indexed.toList()..sort((a, b) => rank(a.$2) != rank(b.$2) ? rank(a.$2) - rank(b.$2) : a.$1 - b.$1);
  return [for (final (_, s) in indexed) s];
}

/// 连接器页页头小标签：“已连接 2 个账户 · 1 个 MCP 服务器”；什么都没接时说清楚。
/// [servers] 为 null = MCP 列表还在加载，这部分先不说。
String connectorSummary(List<Connector> accounts, List<McpServerItem>? servers) {
  final n = accounts.where((c) => c.connected).length;
  final parts = [
    if (n > 0) '已连接 $n 个账户',
    if (servers != null && servers.isNotEmpty) '${servers.length} 个 MCP 服务器',
    if (servers != null && servers.any((s) => s.problemText != null)) '${servers.where((s) => s.problemText != null).length} 个需要处理',
  ];
  return parts.isEmpty ? '还没有连接任何服务' : parts.join(' · ');
}

/// 保险箱分组：网站登录（云浏览器里代填）与 API Key（按域名进请求头）严格分开。
({List<SecretItem> logins, List<SecretItem> keys}) groupSecrets(List<SecretItem> list) =>
    (logins: [for (final s in list) if (s.isLogin) s], keys: [for (final s in list) if (!s.isLogin) s]);

/// 保险箱页头小标签：“1 个网站登录 · 2 个 API Key”。
String vaultSummary(List<SecretItem> list) {
  final g = groupSecrets(list);
  final parts = [
    if (g.logins.isNotEmpty) '${g.logins.length} 个网站登录',
    if (g.keys.isNotEmpty) '${g.keys.length} 个 API Key',
  ];
  return parts.isEmpty ? '保险箱是空的' : parts.join(' · ');
}

/// 一行里的脱敏说明：登录 → 用户名；Key → ••••末四位。永远不含明文。
String secretHint(SecretItem s) => s.isLogin ? (s.username ?? '') : (s.preview.isEmpty ? '' : '••••${s.preview}');

/// 保险箱里能存的两类，起步卡和“存入什么？”菜单共用一份文案。
const secretKinds = [
  (kind: 'login', label: '网站登录', desc: '我在云浏览器里替你登录这个网站'),
  (kind: 'api_key', label: 'API Key', desc: '我调用这个服务时按域名带上它'),
];
