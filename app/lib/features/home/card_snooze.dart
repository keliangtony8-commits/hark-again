// Home 卡片的“稍后提醒”：建议卡（“稍后提醒”）和收件箱报告（“稍后再看”，v1.09）先收起，到点服务端放回并重新标未读（规则在 backend app/card_snooze.py）。
// 客户端只看 snoozedUntil 是否为空来藏卡，不比本机时钟。这里是唯一入口：
// - showSnoozeSheet：卡上“稍后”按钮 → 选时刻（与一次性任务同一张快捷时刻表 models/time_shortcuts.dart）
// - SnoozedCards：“为你准备”/“收件箱”底部一行“N 条稍后提醒|稍后再看 · 最早 …”，点开可以现在放回
// 叫法只由 snoozeNoun(kind) 决定，两端同一张表。
// 网页版 features/home/snooze.tsx 同规则。
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/resource.dart';
import '../../models/resources.dart';
import '../../models/time_shortcuts.dart';
import '../../theme/app_theme.dart';
import '../../theme/tokens.dart';
import '../../ui/format.dart';
import '../../ui/kit.dart';
import '../../ui/motion.dart';
import '../../ui/sheets.dart';
import 'inbox.dart';

/// 这类卡推迟的叫法：建议是“稍后提醒”，报告是“稍后再看”。
String snoozeNoun(String kind) => kind == 'report' ? '稍后再看' : '稍后提醒';

/// 推迟到 [until]；null = 现在放回。推迟会清未读，所以顺手刷新收件箱角标。
Future<void> snoozeCard(WidgetRef ref, HomeCard card, DateTime? until) async {
  await ref.read(cardsProvider.notifier).patch(card.id, {'snoozed_until': until?.toUtc().toIso8601String()});
  await ref.read(inboxProvider.notifier).refresh();
}

/// 选一个时刻推迟这张卡。[now] 供测试注入。
Future<void> showSnoozeSheet(BuildContext context, WidgetRef ref, HomeCard card, {DateTime? now}) async {
  final at = await showActionSheet<DateTime>(context, title: snoozeNoun(card.kind), actions: [
    for (final (label, t) in onceShortcuts(now ?? DateTime.now())) SheetAction(Icons.schedule_rounded, label, value: t),
  ]);
  if (at == null) return;
  try {
    await snoozeCard(ref, card, at);
    final back = card.kind == 'report' ? '放回收件箱' : '再提醒你';
    if (context.mounted) showToast(context, '先收起来，${formatWhen(at, now: now)} $back');
  } catch (e) {
    if (context.mounted) showToast(context, '没推迟成功：$e');
  }
}

/// 段落底部的一行：有推迟中的卡才出现（RiseSwitcher 展开/收起）。[noun] 用 snoozeNoun(kind)。
class SnoozedCards extends ConsumerWidget {
  const SnoozedCards({super.key, required this.cards, this.noun = '稍后提醒', this.now});
  final List<HomeCard> cards; // 只含 snoozed 的
  final String noun;
  final DateTime? now;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final sorted = [...cards]..sort((a, b) => a.snoozedUntil!.compareTo(b.snoozedUntil!));
    Future<void> pick() async {
      final card = await showActionSheet<HomeCard>(context, title: '点一条，现在放回主页', actions: [
        for (final c in sorted) SheetAction(Icons.snooze_rounded, '${c.title} · ${formatWhen(c.snoozedUntil, now: now)}', value: c),
      ]);
      if (card != null) await snoozeCard(ref, card, null);
    }

    final p = context.palette;
    return RiseSwitcher(
      child: sorted.isEmpty
          ? const SizedBox.shrink(key: ValueKey('none'))
          : Pressable(
              key: const ValueKey('snoozed'),
              onTap: pick,
              semanticLabel: '${sorted.length} 条$noun',
              child: ConstrainedBox(
                constraints: const BoxConstraints(minHeight: A11y.minTap),
                child: Row(children: [
                  Icon(Icons.snooze_rounded, size: Fs.md, color: p.text3),
                  const SizedBox(width: Sp.x2),
                  Expanded(
                    child: Text('${sorted.length} 条$noun · 最早 ${formatWhen(sorted.first.snoozedUntil, now: now)}',
                        style: context.text.bodySmall?.copyWith(color: p.text2), maxLines: 1, overflow: TextOverflow.ellipsis),
                  ),
                  Icon(Icons.chevron_right_rounded, size: Fs.lg, color: p.text3),
                ]),
              ),
            ),
    );
  }
}
