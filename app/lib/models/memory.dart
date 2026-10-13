// 记忆页的纯逻辑：分类名、分类计数、搜索+分类筛选，以及“我对你的了解”的数据形状。
// 不碰界面，测试直接调。记忆全量本来就在列表里（单用户几百条），筛选在客户端做，不打服务器。
import 'block.dart';
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

/// 页头小标签：“记得 12 件事 · 4 个分类 · 3 篇笔记”（笔记 v2.21）。
String memorySummary(List<MemoryItem> list, {int notes = 0}) {
  final tail = notes > 0 ? '$notes 篇笔记' : null;
  if (list.isEmpty) return tail ?? '还没有记忆';
  final n = categoryCounts(list).length;
  final head = n > 1 ? '记得 ${list.length} 件事 · $n 个分类' : '记得 ${list.length} 件事';
  return tail == null ? head : '$head · $tail';
}

/// 条数到这个数才显示搜索框（少的时候一眼就看完，搜索框只是噪音）。和技能页同一个门槛。
const memorySearchFrom = 7;

/// 空记忆页的起步按钮：带着例句打开“新增记忆”表单，用户改完点“记住”才保存。
const memoryStarters = [
  (label: '怎么称呼你', content: '叫我', category: 'profile'),
  (label: '饮食忌口', content: '我不吃', category: 'food'),
  (label: '作息习惯', content: '早上 8 点前别打扰我', category: 'general'),
];

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

/// 聊天里记忆卡的当前状态（对照记忆列表推算，所以重开对话、在记忆页手动改过也一致）。
enum MemoryCardState {
  /// 列表还没拿到：只显示，不给撤销键。
  unknown,

  /// 改动仍然生效：可撤销。
  active,

  /// 已撤销（saved 的删了 / updated 的改回去了 / forgotten 的又恢复了）。
  undone,

  /// 记忆后来被别处改动或删掉，和这张卡已对不上：只显示。
  diverged,
}

MemoryCardState memoryCardState(MemoryBlock b, List<MemoryItem>? list) {
  if (list == null || b.items.isEmpty) return MemoryCardState.unknown;
  final byId = {for (final m in list) m.id: m};
  final contents = {for (final m in list) m.content};
  switch (b.action) {
    case 'saved':
      if (b.items.every((i) => !byId.containsKey(i.id))) return MemoryCardState.undone;
      return MemoryCardState.active;
    case 'updated':
      final now = [for (final i in b.items) byId[i.id]];
      if (now.any((m) => m == null)) return MemoryCardState.diverged;
      if ([for (final (k, i) in b.items.indexed) now[k]!.content == i.previous].every((x) => x)) return MemoryCardState.undone;
      if ([for (final (k, i) in b.items.indexed) now[k]!.content == i.content].every((x) => x)) return MemoryCardState.active;
      return MemoryCardState.diverged;
    case 'forgotten':
      if (b.items.every((i) => contents.contains(i.content))) return MemoryCardState.undone;
      return MemoryCardState.active;
  }
  return MemoryCardState.unknown;
}
