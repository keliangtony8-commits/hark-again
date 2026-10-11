// Pages 页的纯逻辑（不碰界面，便于测试）：在线 / 已下线分组、页头摘要、起步提示。
// 网页版 frontend/src/features/me/pageLibrary.ts 与此同规则。
import '../../models/resources.dart';

/// 分成在线与已下线两组，组内按最近更新在前（没有时间的排最后，同时间保持服务器顺序）。
({List<PageItem> live, List<PageItem> off}) groupPages(List<PageItem> list) {
  final sorted = list.indexed.toList()
    ..sort((a, b) {
      final ta = a.$2.updatedAt, tb = b.$2.updatedAt;
      if (ta == null || tb == null) return ta == tb ? a.$1 - b.$1 : (ta == null ? 1 : -1);
      final c = tb.compareTo(ta);
      return c != 0 ? c : a.$1 - b.$1;
    });
  final pages = [for (final (_, p) in sorted) p];
  return (live: [for (final p in pages) if (p.published) p], off: [for (final p in pages) if (!p.published) p]);
}

/// 页头小标签：“3 个网页在线 · 1 个已下线”。
String pagesSummary(List<PageItem> list) {
  final g = groupPages(list);
  final parts = [
    if (g.live.isNotEmpty) '${g.live.length} 个网页在线',
    if (g.off.isNotEmpty) '${g.off.length} 个已下线',
  ];
  return parts.isEmpty ? '还没有网页' : parts.join(' · ');
}

/// 空列表时的起步按钮：点了就开一段新对话把这句话发出去（我来做页面），不会直接建任何东西。
const pageStarters = [
  (label: '行程页', prompt: '把我接下来的行程做成一个网页，方便发给同行的人'),
  (label: '邀请函', prompt: '帮我做一个聚会邀请函网页：时间、地点、怎么到'),
  (label: '个人主页', prompt: '帮我做一个简单的个人主页，先问我要放哪些内容'),
];
