// 用量与花费（本月一次调用都没有 → 概览卡下面一张说明卡，不画全零的图）：一张概览卡（本月花了多少、对比预算 / 上月同期、今天、调用次数），本月每天（usage_chart.dart，选一天看它按模型拆分：usage_day.dart）、最花钱的对话（点开跳进去；已删的合并一行；只露前 3 行，“全部 N 个 ›”进 /me/usage/conversations）、按模型拆分（前 3 行，“全部 ›”进 /me/usage/models）、自动选模型的账（usage_router.dart，没用过“自动”不显示）。数据只读，来自 GET /api/usage。
// 右上角导出：本月报表 → CSV（models/usage_csv.dart）→ 系统分享面板，不多发请求。
// 我的页那一行也读同一个 provider，显示“本月 ¥x / ¥预算”。
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/swr.dart';
import '../../core/share.dart';
import '../../models/usage.dart';
import '../../models/usage_csv.dart';
import '../../theme/app_theme.dart';
import '../../theme/tokens.dart';
import '../../ui/format.dart';
import '../../ui/kit.dart';
import '../../ui/sub_page.dart';
import '../../ui/motion.dart';
import '../chat/open_conversation.dart';
import 'usage_chart.dart';
import 'usage_day.dart';
import 'usage_router.dart';

/// 用量报表：SWR（core/swr.dart），落盘——再进页面、冷启动都先显示上次的报表，后台再取新的。
final usageProvider = swrGet<UsageReport>('/api/usage', (j) => UsageReport.fromJson(jsonMap(j)), diskKey: 'usage');

/// 我的页那一行的副标题；没加载到就给一句静态说明。
String usageSubtitle(UsageReport? r) {
  if (r == null) return '模型 token 和花费，按天、按月统计';
  final spent = r.priced.isEmpty ? '本月 ${formatTokens(r.month.tokens)} token' : '本月 ${formatMoney(r.month.cost, r.currency)}';
  return r.budget == null ? spent : '$spent / 预算 ${formatMoney(r.budget!, r.currency)}';
}

Color budgetColor(Palette p, BudgetLevel l) => switch (l) { BudgetLevel.ok => p.accent, BudgetLevel.near => p.warning, BudgetLevel.over => p.danger };

class UsageScreen extends ConsumerWidget {
  const UsageScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final value = ref.watch(usageProvider);
    return SubPage(
      title: const Text('用量与花费'),
      actions: [_ExportButton(value.value)],
      // 只有第一次没数据才是骨架；之后再进来首帧就是上次的报表（SWR），后台取到新的数字从旧值滚到新值（CountUp）
      body: FadeSwitcher(
        child: value.swr(
          loading: () => const PageBody(key: ValueKey('loading'), children: [_ReportSkeleton()]),
          error: (e) => PageBody(key: const ValueKey('error'), children: [
            EmptyHint(
              icon: Icons.cloud_off_rounded,
              title: '加载失败',
              text: '$e',
              action: OutlinedButton(onPressed: () => ref.invalidate(usageProvider), child: const Text('重试')),
            ),
          ]),
          data: (r) => PullRefresh(
            key: const ValueKey('data'),
            onRefresh: () {
              ref.invalidate(usageDayProvider); // 选中那天的明细也后台重取（有缓存照常显示）
              return ref.read(usageProvider.notifier).reload();
            },
            child: _Report(r),
          ),
        ),
      ),
    );
  }
}

/// 加载中的骨架：形状跟报表一致（概览卡 → 每日图），换成内容时不跳版。
class _ReportSkeleton extends StatelessWidget {
  const _ReportSkeleton();

  @override
  Widget build(BuildContext context) => const Column(children: [
        Shimmer(height: Layout.skeletonHero + Layout.skeletonStat, radius: Radii.card),
        SizedBox(height: Sp.x3),
        Shimmer(height: Layout.skeletonChart, radius: Radii.card),
      ]);
}

/// 导出本月 CSV。报表还没加载到（或加载失败）时置灰；分享面板锚在按钮上（iPad 要用）。
class _ExportButton extends StatelessWidget {
  const _ExportButton(this.report);
  final UsageReport? report;

  Future<void> _export(BuildContext context, UsageReport r) async {
    final box = context.findRenderObject() as RenderBox?;
    final origin = box == null ? null : box.localToGlobal(Offset.zero) & box.size;
    try {
      await shareTextFile(usageCsvFileName(r), usageCsv(r), mime: 'text/csv', origin: origin);
    } catch (_) {
      if (context.mounted) showToast(context, '这台设备打不开分享面板');
    }
  }

  @override
  Widget build(BuildContext context) {
    final r = report;
    return IconButton(
      key: const Key('usage-export'),
      tooltip: '导出本月 CSV',
      icon: const Icon(Icons.ios_share_rounded),
      onPressed: r == null ? null : () => _export(context, r),
    );
  }
}

class _Report extends StatelessWidget {
  const _Report(this.r);
  final UsageReport r;

  @override
  Widget build(BuildContext context) {
    final money = r.priced.isNotEmpty;
    return PageBody(children: [
      FadeSlideIn(child: _MonthCard(r)),
      if (r.idle)
        const EmptyHint(
          key: Key('usage-idle'),
          icon: Icons.insights_rounded,
          title: '本月还没有用量',
          text: '和助手聊上几句，这里会按天画出用量，并列出最花钱的对话和各个模型的花费。',
        ),
      if (r.daily.isNotEmpty && !r.idle) ...[
        const SectionTitle('本月每天'),
        FadeSlideIn(delay: Motion.stagger(2), child: AppCard(
            child: DailyUsageChart(report: r, detail: (day, today) => DayBreakdown(report: r, day: day, today: today)),
          )),
      ],
      if (r.conversations.isNotEmpty) ...[
        SectionTitle('本月最花钱的对话',
            trailing: TopConversationList.rowsOf(r.conversations).length > previewRows
                ? _AllButton(key: const Key('usage-all-conversations'), label: '全部 ${r.conversations.length} 个', to: '/me/usage/conversations')
                : null),
        FadeSlideIn(delay: Motion.stagger(3), child: TopConversationList(report: r, limit: previewRows)),
      ],
      if (r.month.models.isNotEmpty) ...[
        SectionTitle('本月按模型',
            trailing: r.month.models.length > previewRows
                ? const _AllButton(key: Key('usage-all-models'), label: '全部', to: '/me/usage/models')
                : null),
        FadeSlideIn(
          delay: Motion.stagger(4),
          child: ModelUsageList(models: r.month.models, priced: r.priced, currency: r.currency, limit: previewRows),
        ),
      ],
      if (r.router case final router?) ...[
        const SectionTitle('自动选模型'),
        FadeSlideIn(delay: Motion.stagger(5), child: RouterUsageCard(usage: router, currency: r.currency, money: money)),
      ],
      if (!money || r.hasUnpriced)
        Padding(
          padding: const EdgeInsets.fromLTRB(Sp.x1, Sp.x4, Sp.x1, 0),
          child: Text(
            key: const Key('usage-price-hint'),
            money ? '未定价模型只统计 token · .env 的 MODEL_PRICES 补单价' : '未配单价，只统计 token · .env 设 MODEL_PRICES 看花费',
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
            style: context.text.labelSmall,
          ),
        ),
    ]);
  }
}

/// 用量页每个列表只露前几行，其余进子页。
const previewRows = 3;

/// 区块标题行尾的“全部 … ›”：进用量页下的子页（/me/usage/:part）。
class _AllButton extends StatelessWidget {
  const _AllButton({super.key, required this.label, required this.to});
  final String label, to;

  @override
  Widget build(BuildContext context) => TextButton(
        onPressed: () => context.push(to),
        child: Text('$label ›', style: context.text.labelSmall?.copyWith(color: context.palette.text2)),
      );
}

/// 用量页的子页：conversations = 本月最花钱的对话全量，models = 本月按模型全量。读同一个 usageProvider（SWR，不多发请求）。
class UsageDetailScreen extends ConsumerWidget {
  const UsageDetailScreen({super.key, required this.part});
  final String part;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final r = ref.watch(usageProvider).value;
    final convs = part == 'conversations';
    return SubPage(
      title: Text(convs ? '本月最花钱的对话' : '本月按模型'),
      body: r == null
          ? const PageBody(children: [Shimmer(height: Layout.skeletonChart, radius: Radii.card)])
          : PageBody(children: [
              convs ? TopConversationList(report: r) : ModelUsageList(models: r.month.models, priced: r.priced, currency: r.currency),
            ]),
    );
  }
}

/// 按模型拆分的列表：用量页“本月按模型”（limit 3，其余进子页）和聊天里的“本对话用量”（不传 limit，全量）共用。
class ModelUsageList extends StatelessWidget {
  const ModelUsageList({super.key, required this.models, required this.priced, required this.currency, this.limit});
  final List<ModelUsage> models;
  final List<String> priced;
  final String currency;

  /// 只显示前几行；null = 全量。
  final int? limit;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    return ListGroup(children: [
      for (final m in limit == null ? models : models.take(limit!))
        ListRow(
          icon: Icons.memory_rounded,
          title: m.model,
          subtitle: [
            '输入 ${formatTokens(m.promptTokens)}',
            '输出 ${formatTokens(m.completionTokens)}',
            '${m.calls} 次',
            ?m.cacheHit,
          ].join(' · '),
          trailing: Text(priced.contains(m.model) ? formatMoney(m.cost, currency) : '未定价',
              style: context.text.titleMedium?.copyWith(color: priced.contains(m.model) ? p.text : p.text3)),
        ),
    ]);
  }
}

/// 本月最花钱的对话：每行标题 + token/次数/占比 + 花费，下面一条细的占比条（MeterBar，同一套动效）。
/// 点一行 → openConversation 跳进去；已删的对话合并成一行“已删除的对话 N 个”（合计，只展示、不可点），排在第一个已删对话的位置。
class TopConversationList extends ConsumerWidget {
  const TopConversationList({super.key, required this.report, this.limit});
  final UsageReport report;

  /// 只显示前几行（合并之后数）；null = 全量。
  final int? limit;

  /// 合并后的行：已删的对话并成一条（id = 'deleted'，calls/tokens/cost 为合计），其余原样、原序。
  static List<(UsageConversation, int)> rowsOf(List<UsageConversation> list) {
    final gone = list.where((c) => c.deleted).toList();
    final merged = UsageConversation(
      id: 'deleted',
      calls: gone.fold(0, (a, c) => a + c.calls),
      tokens: gone.fold(0, (a, c) => a + c.tokens),
      cost: gone.fold(0.0, (a, c) => a + c.cost),
    );
    final rows = <(UsageConversation, int)>[];
    var placed = false;
    for (final c in list) {
      if (!c.deleted) {
        rows.add((c, 1));
      } else if (!placed) {
        rows.add((merged, gone.length));
        placed = true;
      }
    }
    return rows;
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final p = context.palette;
    final money = report.priced.isNotEmpty;
    final rows = rowsOf(report.conversations);
    return ListGroup(children: [
      for (final (c, n) in limit == null ? rows : rows.take(limit!)) _row(context, ref, c, n, p, money),
    ]);
  }

  Widget _row(BuildContext context, WidgetRef ref, UsageConversation c, int n, Palette p, bool money) {
    final share = report.shareOf(c);
    final body = Column(mainAxisSize: MainAxisSize.min, children: [
      ListRow(
        icon: c.deleted ? Icons.delete_outline_rounded : Icons.chat_bubble_outline_rounded,
        title: c.title ?? '已删除的对话 $n 个',
        subtitle: '${c.deleted ? '合计 ' : ''}${formatTokens(c.tokens)} token · ${c.calls} 次 · 占本月 ${(share * 100).round()}%',
        trailing: Row(mainAxisSize: MainAxisSize.min, children: [
          Text(money ? formatMoney(c.cost, report.currency) : formatTokens(c.tokens),
              style: context.text.titleMedium?.copyWith(color: c.deleted ? p.text3 : p.text)),
          if (!c.deleted) ...[const SizedBox(width: Sp.x1), Icon(Icons.chevron_right_rounded, color: p.text3)],
        ]),
      ),
      Padding(
        padding: const EdgeInsetsDirectional.fromSTEB(Sp.x4, 0, Sp.x4, Sp.x3),
        child: MeterBar(value: share, color: c.deleted ? p.text3 : p.ink, height: Sp.x1),
      ),
    ]);
    if (c.deleted) return KeyedSubtree(key: Key('top-conv-${c.id}'), child: body);
    return InkWell(
      key: Key('top-conv-${c.id}'),
      borderRadius: BorderRadius.circular(Radii.inner),
      onTap: () => openConversation(context, ref, c.id),
      child: body,
    );
  }
}

class _MonthCard extends StatelessWidget {
  const _MonthCard(this.r);
  final UsageReport r;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final ratio = r.budgetRatio;
    final color = budgetColor(p, r.level);
    final money = r.priced.isNotEmpty;
    return AppCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('本月', style: context.text.labelSmall),
        const SizedBox(height: Sp.x1),
        Semantics(
          label: '本月已用 ${money ? formatMoney(r.month.cost, r.currency) : '${formatTokens(r.month.tokens)} token'}',
          excludeSemantics: true,
          child: CountUp(money ? formatMoney(r.month.cost, r.currency) : formatTokens(r.month.tokens),
              style: context.text.headlineMedium?.copyWith(color: p.text)),
        ),
        if (r.lastMonth != null) ...[
          const SizedBox(height: Sp.x2),
          MonthCompare(report: r),
        ],
        if (ratio != null) ...[
          const SizedBox(height: Sp.x3),
          MeterBar(key: const Key('budget-meter'), value: ratio, color: color),
          const SizedBox(height: Sp.x2),
          Text(
            switch (r.level) {
              BudgetLevel.over => '已超出预算 ${formatMoney(r.month.cost - r.budget!, r.currency)}（预算 ${formatMoney(r.budget!, r.currency)}）',
              _ => '预算 ${formatMoney(r.budget!, r.currency)} · 还剩 ${formatMoney(r.budget! - r.month.cost, r.currency)}（${(ratio * 100).round()}%）',
            },
            style: context.text.bodySmall?.copyWith(color: r.level == BudgetLevel.ok ? null : color),
          ),
        ] else if (money) ...[
          const SizedBox(height: Sp.x1),
          Text('未设预算', style: context.text.bodySmall),
        ] else ...[
          const SizedBox(height: Sp.x1),
          Text('token', style: context.text.bodySmall),
        ],
        // 同一张卡里：今天 + 本月调用次数（以前是两张小卡，“本月 token”和大数字重复）
        const SizedBox(height: Sp.x3),
        const Divider(height: 1),
        const SizedBox(height: Sp.x3),
        Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Expanded(child: _Stat(
            key: const Key('usage-today'),
            label: '今天',
            value: money ? formatMoney(r.today.cost, r.currency) : formatTokens(r.today.tokens),
            note: '${r.today.calls} 次调用',
          )),
          const SizedBox(width: Sp.x3),
          Expanded(child: _Stat(
            key: const Key('usage-calls'),
            label: '本月调用',
            value: '${r.month.calls} 次',
            note: money ? '${formatTokens(r.month.tokens)} token' : '本月合计',
          )),
        ]),
      ]),
    );
  }
}

/// 月卡里的“比上月同期”：涨跌小标签 + 上月全月作参照。口径同大数字（有定价按钱，否则 token）。
/// 涨用 warning、降用 accent（花得少是好事）、±5% 以内算持平用中性色；上月同期为 0 时只给一句说明。
class MonthCompare extends StatelessWidget {
  const MonthCompare({super.key, required this.report});
  final UsageReport report;

  static const flatWithin = 0.05;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final lm = report.lastMonth!;
    final money = report.comparesMoney;
    final whole = money ? formatMoney(lm.total.cost, report.currency) : '${formatTokens(lm.total.tokens)} token';
    final d = report.monthDelta;
    if (d == null) {
      final idle = (money ? lm.total.cost : lm.total.tokens) <= 0;
      return Text(idle ? '上月没有用量' : '上月同期没有用量 · 上月全月 $whole', style: context.text.bodySmall);
    }
    final flat = d.abs() < flatWithin;
    final color = flat ? p.text2 : (d > 0 ? p.warning : p.text2);
    final pct = d > 9.99 ? '${(d + 1).toStringAsFixed(0)} 倍' : '${(d.abs() * 100).round()}%';
    final label = flat ? '与上月同期持平' : '比上月同期${d > 0 ? '多' : '少'} $pct';
    final chip = Container(
      padding: const EdgeInsets.symmetric(horizontal: Sp.x2, vertical: Sp.x1 / 2),
      decoration: BoxDecoration(color: color.withValues(alpha: 0.12), borderRadius: BorderRadius.circular(Radii.full)),
      child: Row(mainAxisSize: MainAxisSize.min, children: [
        Icon(flat ? Icons.trending_flat_rounded : (d > 0 ? Icons.trending_up_rounded : Icons.trending_down_rounded), size: Fs.sm, color: color),
        const SizedBox(width: Sp.x1),
        Text(flat ? '持平' : '${d > 0 ? '+' : '−'}$pct', style: context.text.labelMedium?.copyWith(color: color)),
      ]),
    );
    return Wrap(spacing: Sp.x2, runSpacing: Sp.x1, crossAxisAlignment: WrapCrossAlignment.center, children: [
      Semantics(
        container: true,
        label: label,
        excludeSemantics: true,
        child: FadeSlideIn(
          key: const Key('month-delta'),
          child: Row(mainAxisSize: MainAxisSize.min, children: [chip, const SizedBox(width: Sp.x2), Text('比上月同期', style: context.text.bodySmall)]),
        ),
      ),
      Text('· 上月全月 $whole', style: context.text.bodySmall),
    ]);
  }
}

/// 概览卡下半的一格（不再自带卡片）。
class _Stat extends StatelessWidget {
  const _Stat({super.key, required this.label, required this.value, required this.note});
  final String label, value, note;

  @override
  Widget build(BuildContext context) => Semantics(
        container: true,
        label: '$label，$value，$note',
        excludeSemantics: true, // 滚动中的中间数不念，只念终值
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(label, style: context.text.labelSmall),
          const SizedBox(height: Sp.x1),
          CountUp(value, style: context.text.titleLarge),
          Text(note, style: context.text.bodySmall),
        ]),
      );
}
