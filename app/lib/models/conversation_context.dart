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
    this.rules = const WorkspaceRules(),
  });

  factory ConversationContext.fromJson(Map<String, dynamic> j) => ConversationContext(
        messages: _int(j['messages']),
        summarized: _int(j['summarized']),
        raw: _int(j['raw']),
        rawChars: _int(j['raw_chars']),
        budget: _int(j['budget']),
        summary: j['summary'] is String ? j['summary'] as String : '',
        compactable: _int(j['compactable']),
        rules: j['instructions'] is Map
            ? WorkspaceRules.fromJson((j['instructions'] as Map).cast<String, dynamic>())
            : const WorkspaceRules(),
      );

  final int messages, summarized, raw, rawChars, budget, compactable;
  final String summary;

  /// 工作区根目录的规则文件（AGENTS.md 一类，后端 workspace_instructions.py）：每轮都进系统提示。
  final WorkspaceRules rules;

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

/// 一个规则文件的现状：status = full（整份每轮都读）| truncated（超预算只读了前 used 字节）| omitted（超预算没读）。
class WorkspaceRule {
  const WorkspaceRule({required this.path, this.bytes = 0, this.used = 0, this.status = 'full'});

  factory WorkspaceRule.fromJson(Map<String, dynamic> j) => WorkspaceRule(
        path: j['path'] is String ? j['path'] as String : '',
        bytes: _int(j['bytes']),
        used: _int(j['used']),
        status: switch (j['status']) { 'truncated' => 'truncated', 'omitted' => 'omitted', _ => 'full' },
      );

  final String path, status;
  final int bytes, used;

  /// 没整份读进去（截断或省掉）：行尾换警示色。
  bool get cut => status != 'full';
}

class WorkspaceRules {
  const WorkspaceRules({this.files = const [], this.budget = 0, this.candidates = const ['AGENTS.md']});

  factory WorkspaceRules.fromJson(Map<String, dynamic> j) => WorkspaceRules(
        files: [
          for (final f in (j['files'] is List ? j['files'] as List : const []))
            if (f is Map) WorkspaceRule.fromJson(f.cast<String, dynamic>()),
        ].where((f) => f.path.isNotEmpty).toList(),
        budget: _int(j['budget']),
        candidates: [for (final c in (j['candidates'] is List ? j['candidates'] as List : const [])) if (c is String) c],
      );

  final List<WorkspaceRule> files;
  final int budget;
  final List<String> candidates;

  /// 预算 0 = 后端关掉了这个功能：卡片不显示这一段。
  bool get enabled => budget > 0;
}
