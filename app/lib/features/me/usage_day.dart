// 用量图上选中某一天 → 那天的明细（挂在 DailyUsageChart 的 detail 位置，同一张卡里）：
//   1. 按模型拆分；2. 那天最花钱的几个对话（点一行 → openConversation 跳进去，已删的不可点）。
// 数据流：一律取 GET /api/usage/days/{date}（今天也取——报表里没有“今天的对话”）；provider 以日期为键，
// SWR（core/swr.dart）：看过的那天再选 / 再进用量页首帧就是明细，后台重取；下拉刷新用量页时一起重取（usage_screen 里 invalidate）。
// 今天在请求途中/失败时先用报表里的 today 画模型行，不闪骨架。
// 图表只在“选定”（点下、拖完、读屏调节）时才换这里的日期，拖动途中不发请求。
// 版面：模型行和对话行是同一种紧凑行（_ShareRow：名字 · 副文 · 钱，下面一条占当天比例的 MeterBar）。
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/swr.dart';
import '../../models/usage.dart';
import '../../theme/app_theme.dart';
import '../../theme/tokens.dart';
import '../../ui/format.dart';
import '../../ui/kit.dart';
import '../../ui/motion.dart';
import '../chat/open_conversation.dart';

String dayKey(DateTime d) =>
    '${d.year.toString().padLeft(4, '0')}-${d.month.toString().padLeft(2, '0')}-${d.day.toString().padLeft(2, '0')}';

final usageDayProvider = swrGetFamily<UsageDayDetail, String>((date) => '/api/usage/days/$date', (j) => UsageDayDetail.fromJson(jsonMap(j)));

/// 某一天的明细。[today] 为真时，请求途中和失败时先用 report.today 画模型行。
class DayBreakdown extends ConsumerWidget {
  const DayBreakdown({super.key, required this.report, required this.day, required this.today});
  final UsageReport report;
  final UsageDay day;
  final bool today;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    if (day.calls == 0) return const SizedBox(width: double.infinity);
    final key = dayKey(day.date);
    final fallback = today ? DayModelRows(models: report.today.models, priced: report.priced, currency: report.currency) : null;
    return ref.watch(usageDayProvider(key)).swr(
          loading: () => fallback ?? const SkeletonList(rows: 1),
          error: (_) => Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            ?fallback,
            _Retry(onTap: () => ref.invalidate(usageDayProvider(key))),
          ]),
          data: (d) => Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            DayModelRows(models: d.usage.total.models, priced: d.usage.priced, currency: d.usage.currency),
            if (d.conversations.isNotEmpty)
              FadeSlideIn(child: DayConversationRows(detail: d, label: today ? '今天最花钱的对话' : '那天最花钱的对话')),
          ]),
        );
  }
}

class _Retry extends StatelessWidget {
  const _Retry({required this.onTap});
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) => Pressable(
        semanticLabel: '那天的明细加载失败，点按重试',
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.symmetric(vertical: Sp.x2),
          child: Row(children: [
            Icon(Icons.refresh_rounded, size: Sp.x4, color: context.palette.text3),
            const SizedBox(width: Sp.x2),
            Text('明细加载失败，点这里重试', style: context.text.bodySmall),
          ]),
        ),
      );
}

/// 紧凑的按模型列表（卡片里用，不再套一层卡）。占比有定价按钱，否则按 token。
class DayModelRows extends StatelessWidget {
  const DayModelRows({super.key, required this.models, required this.priced, required this.currency});
  final List<ModelUsage> models;
  final List<String> priced;
  final String currency;

  @override
  Widget build(BuildContext context) {
    final money = priced.isNotEmpty && models.any((m) => m.cost > 0);
    final total = models.fold<double>(0, (s, m) => s + (money ? m.cost : m.tokens.toDouble()));
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      for (final m in models)
        _ShareRow(
          key: Key('day-model-${m.model}'),
          label: m.model,
          sub: '${formatTokens(m.tokens)} token · ${m.calls} 次',
          amount: priced.contains(m.model) ? formatMoney(m.cost, currency) : '未定价',
          muted: !priced.contains(m.model),
          share: total <= 0 ? 0 : ((money ? m.cost : m.tokens.toDouble()) / total).clamp(0.0, 1.0),
        ),
    ]);
  }
}

/// 那天最花钱的对话：小标题 + 紧凑行；点一行跳进对话，已删的灰掉、不可点。
class DayConversationRows extends ConsumerWidget {
  const DayConversationRows({super.key, required this.detail, required this.label});
  final UsageDayDetail detail;
  final String label;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final u = detail.usage;
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Padding(
        padding: const EdgeInsets.only(top: Sp.x4),
        child: Text(label, style: context.text.labelSmall),
      ),
      for (final c in detail.conversations)
        _ShareRow(
          key: Key('day-conv-${c.id}'),
          label: c.title ?? '已删除的对话',
          sub: '${formatTokens(c.tokens)} token · ${c.calls} 次',
          amount: u.money ? formatMoney(c.cost, u.currency) : formatTokens(c.tokens),
          muted: c.deleted,
          share: detail.shareOf(c),
          onTap: c.deleted ? null : () => openConversation(context, ref, c.id),
        ),
    ]);
  }
}

/// 一行“名字  副文 …… 钱”，下面一条细的份额条。有 [onTap] 时整行可点、尾部带箭头。
class _ShareRow extends StatelessWidget {
  const _ShareRow({super.key, required this.label, required this.sub, required this.amount, required this.share, this.muted = false, this.onTap});
  final String label, sub, amount;
  final double share;
  final bool muted;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final row = Padding(
      padding: const EdgeInsets.only(top: Sp.x2),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Expanded(
            child: Text.rich(
              TextSpan(children: [
                TextSpan(text: label, style: context.text.bodyMedium?.copyWith(color: muted ? p.text3 : p.text)),
                TextSpan(text: '  $sub', style: context.text.bodySmall),
              ]),
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
            ),
          ),
          Text(amount, style: context.text.bodyMedium?.copyWith(color: muted ? p.text3 : p.text)),
          if (onTap != null) Icon(Icons.chevron_right_rounded, size: Sp.x4, color: p.text3),
        ]),
        const SizedBox(height: Sp.x1),
        MeterBar(value: share, color: muted ? p.text3 : p.ink, height: Sp.x1),
      ]),
    );
    if (onTap == null) return row;
    return Pressable(semanticLabel: '$label，$amount，打开对话', onTap: onTap, child: row);
  }
}
