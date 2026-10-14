// 反馈（v2.64，对标 Hark 设置 → Feedback + 回复下的 👍 / 👎）：服务器 /api/feedback 的数据和两端共用的文字规则。
// 报告里存什么、一条回复几份评价只在后端 app/feedback.py；这里只解析 + 决定怎么说（纯函数，test/feedback_test.dart 覆盖）。
import '../ui/format.dart';

/// 👍 的评价值；其余是 👎 的原因（顺序 = 原因单里的顺序，和网页 lib/feedback.ts 一致）。
const feedbackGood = 'good';
const feedbackReasons = <(String, String)>[
  ('wrong', '答错了'),
  ('incomplete', '没做完'),
  ('stuck', '响应缓慢或无响应'),
  ('other', '别的问题'),
];

bool isBadFeedback(String? kind) => kind != null && kind != feedbackGood;

class FeedbackItem {
  const FeedbackItem({
    required this.id,
    required this.kind,
    required this.kindLabel,
    required this.excerpt,
    required this.resolved,
    this.messageId,
    this.conversationId,
    this.projectId,
    this.createdAt,
    this.note = '',
    this.markdown = '',
    this.snapshot = const {},
  });
  final String id, kind, kindLabel, excerpt, note, markdown;
  final bool resolved;
  final String? messageId, conversationId, projectId;
  final DateTime? createdAt;

  /// 详情才有（列表里是空的）：提问 / 回复 / 步骤 / 轨迹 / 模型。
  final Map<String, dynamic> snapshot;

  bool get good => kind == feedbackGood;
  bool get problem => kind == 'problem';

  factory FeedbackItem.fromJson(Map<String, dynamic> j) => FeedbackItem(
        id: '${j['id'] ?? ''}',
        kind: '${j['kind'] ?? 'other'}',
        kindLabel: '${j['kind_label'] ?? ''}',
        excerpt: '${j['excerpt'] ?? ''}',
        resolved: j['status'] == 'resolved',
        messageId: j['message_id'] as String?,
        conversationId: j['conversation_id'] as String?,
        projectId: j['project_id'] as String?,
        createdAt: j['created_at'] is String ? DateTime.tryParse(j['created_at'] as String)?.toLocal() : null,
        note: '${j['note'] ?? ''}',
        markdown: '${j['markdown'] ?? ''}',
        snapshot: j['snapshot'] is Map ? Map<String, dynamic>.from(j['snapshot'] as Map) : const {},
      );
}

class FeedbackList {
  const FeedbackList({this.items = const [], this.open = 0});
  final List<FeedbackItem> items;

  /// 没解决的（👍 不算）：“我的 → 反馈”行尾的数字。
  final int open;

  factory FeedbackList.fromJson(dynamic j) {
    final m = j is Map ? j : const {};
    return FeedbackList(
      items: [for (final x in m['items'] as List? ?? const []) FeedbackItem.fromJson(Map<String, dynamic>.from(x as Map))],
      open: (m['open'] as num?)?.toInt() ?? 0,
    );
  }
}

/// 列表一行的副标题：“答错了 · 3 小时前”；已解决的加“已解决”。
String feedbackLine(FeedbackItem f, {DateTime? now}) =>
    [f.kindLabel, if (f.createdAt != null) formatAgo(f.createdAt, now: now), if (f.resolved) '已解决'].join(' · ');

/// 打完评价的提示：👍 一句谢谢；👎 告诉他报告存在哪。
String feedbackToast(String? kind) => switch (kind) {
      null => '已取消评价',
      feedbackGood => '谢谢，记下了',
      _ => '已记下，可在“我的 → 反馈”里查看',
    };

/// “我的”入口副标题：有没解决的就说几条。
String feedbackRowSubtitle(FeedbackList? l) =>
    l == null || l.open == 0 ? '报告问题，回看评价过的回复' : '${l.open} 条没解决';
