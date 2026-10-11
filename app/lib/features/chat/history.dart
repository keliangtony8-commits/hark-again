// 历史对话的分组规则（纯函数，可测）：置顶 / 今天 / 昨天 / 7 天内 / 更早。
import '../../models/resources.dart';

typedef HistoryGroup = ({String label, List<ConversationSummary> items});

List<HistoryGroup> groupConversations(List<ConversationSummary> list, {DateTime? now}) {
  final today = _day(now ?? DateTime.now());
  final buckets = <String, List<ConversationSummary>>{for (final l in const ['置顶', '今天', '昨天', '7 天内', '更早']) l: []};
  for (final c in list) {
    final t = c.updatedAt;
    final days = t == null ? 999 : today.difference(_day(t)).inDays;
    final label = c.pinned
        ? '置顶'
        : days <= 0
            ? '今天'
            : days == 1
                ? '昨天'
                : days < 7
                    ? '7 天内'
                    : '更早';
    buckets[label]!.add(c);
  }
  return [for (final e in buckets.entries) if (e.value.isNotEmpty) (label: e.key, items: e.value)];
}

DateTime _day(DateTime t) => DateTime(t.year, t.month, t.day);
