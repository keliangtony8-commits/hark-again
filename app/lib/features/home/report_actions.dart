// 收件箱的一行报告 + 它的操作（v1.09，对标 Hark 收件箱条目可以“稍后再看”/收起）。
// 唯一入口：Home“收件箱”卡（InboxCard，v2.78 卡片栈里的一张）的每一行都是 InboxRow；操作只在 showReportActions 里——
// - 稍后再看 → card_snooze.dart showSnoozeSheet（同一张快捷时刻表；到点服务端放回并重新未读，横幅再弹一次）
// - 标为已读（只在未读时给）→ inboxProvider.markRead([id])
// - 收起 → PATCH dismissed（报告只是隐藏，对话还在“对话”里）
// 点行 = 打开报告对话（onOpen）；长按或行尾“更多”钮 = 操作表。网页版 features/home/InboxRow.tsx 同规则。
import 'package:flutter/material.dart';
import 'package:flutter/semantics.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/resource.dart';
import '../../models/resources.dart';
import '../../theme/app_theme.dart';
import '../../theme/tokens.dart';
import '../../ui/kit.dart';
import '../../ui/motion.dart';
import '../../ui/sheets.dart';
import 'card_snooze.dart';
import 'inbox.dart';
import 'stack_card.dart';

enum ReportAction { snooze, read, dismiss }

/// 这条报告能做的操作（顺序即操作表顺序）。纯规则，测试直接调。
List<ReportAction> reportActionsOf(HomeCard card) =>
    [ReportAction.snooze, if (card.unread) ReportAction.read, ReportAction.dismiss];

Future<void> showReportActions(BuildContext context, WidgetRef ref, HomeCard card, {DateTime? now}) async {
  const labels = {ReportAction.snooze: '稍后再看', ReportAction.read: '标为已读', ReportAction.dismiss: '收起'};
  const icons = {
    ReportAction.snooze: Icons.snooze_rounded,
    ReportAction.read: Icons.mark_email_read_outlined,
    ReportAction.dismiss: Icons.inventory_2_outlined,
  };
  final picked = await showActionSheet<ReportAction>(context, title: card.title, actions: [
    for (final a in reportActionsOf(card)) SheetAction(icons[a]!, labels[a]!, value: a),
  ]);
  if (picked == null || !context.mounted) return;
  try {
    switch (picked) {
      case ReportAction.snooze:
        await showSnoozeSheet(context, ref, card, now: now);
      case ReportAction.read:
        await ref.read(inboxProvider.notifier).markRead([card.id]);
      case ReportAction.dismiss:
        await ref.read(cardsProvider.notifier).patch(card.id, {'dismissed': true});
        await ref.read(inboxProvider.notifier).refresh();
        if (context.mounted) showToast(context, '已收起，对话还在“对话”里');
    }
  } catch (e) {
    if (context.mounted) showToast(context, '没办成：$e');
  }
}

/// 收件箱一行：行首收件箱图标（未读时强调色小点），标题 + 一眼摘要，行尾时间 + “更多”钮。
class InboxRow extends ConsumerWidget {
  const InboxRow({super.key, required this.card, required this.time, required this.onOpen});
  final HomeCard card;
  final String time;
  final VoidCallback onOpen;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final p = context.palette;
    void more() => showReportActions(context, ref, card);
    return Semantics(
      customSemanticsActions: {const CustomSemanticsAction(label: '稍后再看或收起'): more},
      child: ListRow(
        leading: DotBadge(visible: card.unread, color: p.accent, child: const IconBadge(Icons.inbox_outlined)),
        title: card.title,
        subtitle: card.glance,
        trailing: Row(mainAxisSize: MainAxisSize.min, children: [
          Text(time, style: context.text.labelSmall),
          IconButton(
            icon: Icon(Icons.more_horiz_rounded, color: p.text3, size: Layout.rowIcon),
            tooltip: '更多',
            constraints: const BoxConstraints(minWidth: A11y.minTap, minHeight: A11y.minTap),
            onPressed: more,
          ),
        ]),
        onTap: onOpen,
        onLongPress: more,
      ),
    );
  }
}

/// 主页“收件箱”卡：最近几条报告（新的在前），卡头“全部已读”只在有未读时出现。没有报告就整张不画。
class InboxCard extends ConsumerWidget {
  const InboxCard({super.key, required this.reports, required this.onOpen});
  final List<HomeCard> reports;
  final void Function(HomeCard) onOpen;

  static String _hm(DateTime? t) => t == null ? '' : '${t.hour.toString().padLeft(2, '0')}:${t.minute.toString().padLeft(2, '0')}';

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final unread = ref.watch(inboxProvider.select((s) => s.unread));
    return RiseSwitcher(
      child: reports.isEmpty
          ? const SizedBox.shrink(key: ValueKey('none'))
          : StackCard(
              key: const ValueKey('inbox'),
              title: '收件箱',
              trailing: FadeSwitcher(
                child: unread > 0
                    ? TextButton(key: const ValueKey('read'), onPressed: () => ref.read(inboxProvider.notifier).markRead(), child: const Text('全部已读'))
                    : const SizedBox.shrink(key: ValueKey('none')),
              ),
              rows: [for (final r in reports) InboxRow(key: ValueKey(r.id), card: r, time: _hm(r.updatedAt), onOpen: () => onOpen(r))],
            ),
    );
  }
}
