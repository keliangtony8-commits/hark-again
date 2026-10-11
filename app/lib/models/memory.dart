// 记忆页的纯逻辑：分类名、分类计数、搜索+分类筛选，以及“我对你的了解”的数据形状。
// 不碰界面，测试直接调。记忆全量本来就在列表里（单用户几百条），筛选在客户端做，不打服务器。
import 'resources.dart';

/// 已知分类的中文名，顺序即显示顺序；服务器给了不认识的分类就原样显示、排在后面。
const memoryCategories = {'profile': '关于你', 'food': '饮食', 'travel': '出行', 'work': '学习工作', 'shopping': '购物', 'general': '其他'};

String categoryLabel(String c) => memoryCategories[c] ?? c;

/// 把分类排成固定顺序：已知的按 [memoryCategories]，未知的按字母。
int _rank(String c) {
  final i = memoryCategories.keys.toList().indexOf(c);
  return i < 0 ? memoryCategories.length : i;
}

int compareCategory(String a, String b) {
  final r = _rank(a).compareTo(_rank(b));
  return r != 0 ? r : a.compareTo(b);
}

/// 每个分类有几条（筛选条的数字），按显示顺序。
List<(String, int)> categoryCounts(List<MemoryItem> list) {
  final counts = <String, int>{};
  for (final m in list) {
    counts[m.category] = (counts[m.category] ?? 0) + 1;
  }
  return [for (final c in counts.keys.toList()..sort(compareCategory)) (c, counts[c]!)];
}

/// 搜索（不分大小写，空格分开的词都要命中，内容或分类中文名都算）+ 分类筛选（null = 全部），
/// 结果按分类分组，组内保持原顺序（服务器已按最近更新排好）。
List<(String, List<MemoryItem>)> filterMemories(List<MemoryItem> list, {String query = '', String? category}) {
  final words = query.toLowerCase().split(RegExp(r'\s+')).where((w) => w.isNotEmpty).toList();
  bool hit(MemoryItem m) {
    final hay = '${m.content}\n${categoryLabel(m.category)}'.toLowerCase();
    return words.every(hay.contains);
  }

  final groups = <String, List<MemoryItem>>{};
  for (final m in list) {
    if (category != null && m.category != category) continue;
    if (!hit(m)) continue;
    groups.putIfAbsent(m.category, () => []).add(m);
  }
  return [for (final c in groups.keys.toList()..sort(compareCategory)) (c, groups[c]!)];
}

/// GET/POST /api/memory-digest 的形状。text 为 null = 还没生成过。
class MemoryDigest {
  const MemoryDigest({this.text, this.generatedAt, this.count = 0, this.memories = 0, this.stale = false});
  factory MemoryDigest.fromJson(Map<String, dynamic> j) => MemoryDigest(
        text: j['text'] as String?,
        generatedAt: j['generated_at'] is String ? DateTime.tryParse(j['generated_at'] as String)?.toLocal() : null,
        count: (j['count'] as num?)?.toInt() ?? 0,
        memories: (j['memories'] as num?)?.toInt() ?? 0,
        stale: j['stale'] as bool? ?? false,
      );
  final String? text;
  final DateTime? generatedAt;
  final int count, memories;
  final bool stale;

  bool get hasText => text != null && text!.isNotEmpty;
}
