// 用量与花费（GET /api/usage）。只读报表：记账在后端 app/usage.py，客户端不算钱。
class ModelUsage {
  const ModelUsage({required this.model, required this.calls, required this.promptTokens, required this.completionTokens, required this.cost});
  factory ModelUsage.fromJson(Map<String, dynamic> j) => ModelUsage(
      model: j['model'] as String? ?? '',
      calls: (j['calls'] as num?)?.toInt() ?? 0,
      promptTokens: (j['prompt_tokens'] as num?)?.toInt() ?? 0,
      completionTokens: (j['completion_tokens'] as num?)?.toInt() ?? 0,
      cost: (j['cost'] as num?)?.toDouble() ?? 0);
  final String model;
  final int calls, promptTokens, completionTokens;
  final double cost;
  int get tokens => promptTokens + completionTokens;
}

class UsagePeriod {
  const UsagePeriod({this.calls = 0, this.tokens = 0, this.cost = 0, this.models = const []});
  factory UsagePeriod.fromJson(Map<String, dynamic>? j) => j == null
      ? const UsagePeriod()
      : UsagePeriod(
          calls: (j['calls'] as num?)?.toInt() ?? 0,
          tokens: (j['tokens'] as num?)?.toInt() ?? 0,
          cost: (j['cost'] as num?)?.toDouble() ?? 0,
          models: [for (final m in (j['models'] as List? ?? const [])) ModelUsage.fromJson((m as Map).cast<String, dynamic>())]);
  final int calls, tokens;
  final double cost;
  final List<ModelUsage> models;
}

/// 本月某一天的用量（报表的 daily 序列，日期是服务器 TIMEZONE 的本地日期）。
class UsageDay {
  const UsageDay({required this.date, this.calls = 0, this.tokens = 0, this.cost = 0});
  factory UsageDay.fromJson(Map<String, dynamic> j) => UsageDay(
      date: DateTime.tryParse(j['date'] as String? ?? '') ?? DateTime(1970),
      calls: (j['calls'] as num?)?.toInt() ?? 0,
      tokens: (j['tokens'] as num?)?.toInt() ?? 0,
      cost: (j['cost'] as num?)?.toDouble() ?? 0);
  final DateTime date; // 只用年月日
  final int calls, tokens;
  final double cost;
}

/// 本月最花钱的对话之一（报表的 conversations，按花费降序）。title 为 null = 对话已删，用量还在。
class UsageConversation {
  const UsageConversation({required this.id, this.title, this.calls = 0, this.tokens = 0, this.cost = 0});
  factory UsageConversation.fromJson(Map<String, dynamic> j) => UsageConversation(
      id: j['id'] as String? ?? '',
      title: j['title'] as String?,
      calls: (j['calls'] as num?)?.toInt() ?? 0,
      tokens: (j['tokens'] as num?)?.toInt() ?? 0,
      cost: (j['cost'] as num?)?.toDouble() ?? 0);
  final String id;
  final String? title;
  final int calls, tokens;
  final double cost;
  bool get deleted => title == null;
}

/// 上个月：全月合计 + 同期（上月 1 号到上月同一天同一时刻，服务器按 TIMEZONE 对齐日历）。
class LastMonthUsage {
  const LastMonthUsage({required this.total, required this.toDate});
  factory LastMonthUsage.fromJson(Map<String, dynamic> j) =>
      LastMonthUsage(total: UsagePeriod.fromJson(j), toDate: UsagePeriod.fromJson((j['to_date'] as Map?)?.cast<String, dynamic>()));
  final UsagePeriod total, toDate; // 只有 calls/tokens/cost，没有按模型拆分
}

/// 预算提醒的三档：只提醒，后端不拦截调用。
enum BudgetLevel { ok, near, over }

class UsageReport {
  const UsageReport({required this.currency, this.budget, this.priced = const [], required this.today, required this.month, this.daily = const [], this.conversations = const [], this.lastMonth});
  factory UsageReport.fromJson(Map<String, dynamic> j) => UsageReport(
      currency: j['currency'] as String? ?? 'CNY',
      budget: (j['budget'] as num?)?.toDouble(),
      priced: [for (final p in (j['priced'] as List? ?? const [])) '$p'],
      today: UsagePeriod.fromJson((j['today'] as Map?)?.cast<String, dynamic>()),
      month: UsagePeriod.fromJson((j['month'] as Map?)?.cast<String, dynamic>()),
      daily: [for (final d in (j['daily'] as List? ?? const [])) UsageDay.fromJson((d as Map).cast<String, dynamic>())],
      conversations: [
        for (final c in (j['conversations'] as List? ?? const [])) UsageConversation.fromJson((c as Map).cast<String, dynamic>())
      ],
      lastMonth: j['last_month'] is Map ? LastMonthUsage.fromJson((j['last_month'] as Map).cast<String, dynamic>()) : null);
  final String currency;
  final double? budget; // null = 没设
  final List<String> priced; // 配了单价的别名；为空时只有 token，没有钱
  final UsagePeriod today, month;
  final List<UsageDay> daily; // 本月 1 号到今天，每天一项（老服务器没有这个字段 → 空）
  final List<UsageConversation> conversations; // 本月最花钱的几个对话（老服务器 → 空）
  final LastMonthUsage? lastMonth; // 上月全月 + 同期（老服务器 → null，不显示对比）

  /// 比较口径：有定价按钱，否则按 token（和月卡大数字同一口径）。
  bool get comparesMoney => priced.isNotEmpty;

  /// 本月至今对比上月同期的涨跌（+0.23 = 多 23%）。老服务器 / 上月同期为 0 → null（没有可比的基数）。
  double? get monthDelta {
    final lm = lastMonth;
    if (lm == null) return null;
    final prev = comparesMoney ? lm.toDate.cost : lm.toDate.tokens.toDouble();
    if (prev <= 0) return null;
    return (comparesMoney ? month.cost : month.tokens.toDouble()) / prev - 1;
  }

  /// 某个对话占本月的份额（0..1）：有定价按钱算，否则按 token；本月为 0 时给 0。
  double shareOf(UsageConversation c) {
    final money = priced.isNotEmpty && month.cost > 0;
    final total = money ? month.cost : month.tokens.toDouble();
    if (total <= 0) return 0;
    return ((money ? c.cost : c.tokens.toDouble()) / total).clamp(0.0, 1.0);
  }

  static const nearAt = 0.8;

  /// 本月有多少天（图表按整月排格子，今天之后的格子空着）。
  int get daysInMonth {
    if (daily.isEmpty) return 0;
    final d = daily.first.date;
    return DateTime(d.year, d.month + 1, 0).day;
  }

  /// 按预算平均到每天该花多少；没设预算或没定价 → null（图表上那条虚线）。
  double? get dailyPace => budget == null || budget! <= 0 || priced.isEmpty || daysInMonth == 0 ? null : budget! / daysInMonth;

  /// 本月已用占预算的比例（可 > 1）；没设预算为 null。
  double? get budgetRatio => budget == null || budget! <= 0 ? null : month.cost / budget!;

  BudgetLevel get level {
    final r = budgetRatio;
    if (r == null || r < nearAt) return BudgetLevel.ok;
    return r < 1 ? BudgetLevel.near : BudgetLevel.over;
  }

  /// 有用量的别名里有没有没定价的（那部分钱算不出来，界面要提示“只统计 token”）。
  bool get hasUnpriced => month.models.any((m) => !priced.contains(m.model));
}

/// 一段用量的合计 + 按模型拆分：单个对话的累计（GET /api/conversations/{id}/usage）和
/// 某一天（GET /api/usage/days/{date}，外面再包一层 UsageDayDetail）共用这一个形状。
class UsageTotal {
  const UsageTotal({required this.currency, this.priced = const [], required this.total});
  factory UsageTotal.fromJson(Map<String, dynamic> j) => UsageTotal(
      currency: j['currency'] as String? ?? 'CNY',
      priced: [for (final p in (j['priced'] as List? ?? const [])) '$p'],
      total: UsagePeriod.fromJson((j['total'] as Map?)?.cast<String, dynamic>()));
  final String currency;
  final List<String> priced;
  final UsagePeriod total;

  /// 配了单价才谈得上钱；否则只显示 token。
  bool get money => priced.isNotEmpty;
  bool get hasUnpriced => total.models.any((m) => !priced.contains(m.model));
}

/// 某一天的明细（GET /api/usage/days/{date}）：按模型拆分（[usage]，同 UsageTotal）+ 那天最花钱的几个对话。
class UsageDayDetail {
  const UsageDayDetail({required this.usage, this.conversations = const []});
  factory UsageDayDetail.fromJson(Map<String, dynamic> j) => UsageDayDetail(
      usage: UsageTotal.fromJson(j),
      conversations: [
        for (final c in (j['conversations'] as List? ?? const [])) UsageConversation.fromJson((c as Map).cast<String, dynamic>())
      ]);
  final UsageTotal usage;
  final List<UsageConversation> conversations; // 老服务器没有这个字段 → 空

  /// 某个对话占当天的份额（0..1），规则同 UsageReport.shareOf：有定价按钱，否则按 token。
  double shareOf(UsageConversation c) {
    final t = usage.total;
    final money = usage.money && t.cost > 0;
    final total = money ? t.cost : t.tokens.toDouble();
    if (total <= 0) return 0;
    return ((money ? c.cost : c.tokens.toDouble()) / total).clamp(0.0, 1.0);
  }
}
