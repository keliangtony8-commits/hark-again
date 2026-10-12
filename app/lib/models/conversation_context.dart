// 对话记忆（GET /api/conversations/{id}/context、POST …/compact，后端 agent/context.py 是唯一规则）：
// 下一轮发给模型的原文多大、较早多少条已压成滚动摘要、还能手动整理几条。客户端只展示，不算。

int _int(Object? v) => v is num ? v.toInt() : 0;

class ConversationContext {
  const ConversationContext({
    this.messages = 0,
    this.summarized = 0,
    this.raw = 0,
    this.rawChars = 0,
    this.budget = 0,
    this.summary = '',
    this.compactable = 0,
  });

  factory ConversationContext.fromJson(Map<String, dynamic> j) => ConversationContext(
        messages: _int(j['messages']),
        summarized: _int(j['summarized']),
        raw: _int(j['raw']),
        rawChars: _int(j['raw_chars']),
        budget: _int(j['budget']),
        summary: j['summary'] is String ? j['summary'] as String : '',
        compactable: _int(j['compactable']),
      );

  final int messages, summarized, raw, rawChars, budget, compactable;
  final String summary;

  /// 原文占预算的比例（满了下一轮会自动折叠）；预算未知 → 0。
  double get fill => budget <= 0 ? 0 : rawChars / budget;

  /// 快满（≥ 80%）：条子换警示色。
  bool get tight => fill >= 0.8;
}

/// 手动整理的结果：status = compressed | noop | inflated；before/after = 原文 + 摘要的字数。
class CompactResult {
  const CompactResult({required this.state, required this.status, this.before = 0, this.after = 0});

  factory CompactResult.fromJson(Map<String, dynamic> j) => CompactResult(
        state: ConversationContext.fromJson(j),
        status: j['status'] is String ? j['status'] as String : 'noop',
        before: _int(j['before']),
        after: _int(j['after']),
      );

  final ConversationContext state;
  final String status;
  final int before, after;
}
