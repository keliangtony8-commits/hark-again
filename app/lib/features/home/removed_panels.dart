// v2.17 移除的面板可以找回（规则在 backend app/panel_trash.py：30 天内，找回后做法都在、马上重新取数据）。
// 这里是客户端唯一入口：
// - removePanel：面板“更多 → 移除”。可撤销，所以不再弹危险确认；底部一条“已移除「X」· 撤销”。
// - RemovedPanels：“面板”段末一行“N 个最近移除的面板”，点开选一个放回。只列服务端说 revivable 的卡。
// 网页版 features/home/RemovedPanels.tsx 同规则。
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api.dart';
import '../../core/resource.dart';
import '../../models/resources.dart';
import '../../theme/app_theme.dart';
import '../../theme/tokens.dart';
import '../../ui/format.dart';
import '../../ui/kit.dart';
import '../../ui/motion.dart';
import '../../ui/sheets.dart';

/// 卡片列表里还能找回的面板，最近移除的在前。
List<HomeCard> removedPanels(Iterable<HomeCard> cards) {
  final out = cards.where((c) => c.kind == 'panel' && c.revivable).toList();
  out.sort((a, b) => (b.removedAt ?? DateTime(0)).compareTo(a.removedAt ?? DateTime(0)));
  return out;
}

Future<void> _reload(WidgetRef ref) =>
    Future.wait([ref.read(cardsProvider.notifier).reload(), ref.read(tasksProvider.notifier).reload()]);

/// 找回一张移除的面板；成功返回 true。
Future<bool> revivePanel(BuildContext context, WidgetRef ref, HomeCard card) async {
  try {
    await ref.read(apiProvider).post('/api/cards/${card.id}/revive');
  } catch (e) {
    if (context.mounted) showToast(context, '没找回来：$e');
    return false;
  }
  await _reload(ref);
  if (context.mounted) showToast(context, '「${card.title}」放回来了，正在重新取数据');
  return true;
}

/// 面板菜单里的“移除”：停止刷新，进“最近移除”，提示条上可以立刻撤销。
Future<void> removePanel(BuildContext context, WidgetRef ref, HomeCard card) async {
  try {
    await ref.read(apiProvider).post('/api/cards/${card.id}/remove');
  } catch (e) {
    if (context.mounted) showToast(context, '没移除成功：$e');
    return;
  }
  await _reload(ref);
  if (!context.mounted) return;
  showToast(context, '已移除「${card.title}」，30 天内可以找回', action: '撤销', onAction: () {
    if (context.mounted) revivePanel(context, ref, card);
  });
}

/// “面板”段末的一行：有可找回的面板才出现（RiseSwitcher 展开/收起），点开选一个放回。
class RemovedPanels extends ConsumerWidget {
  const RemovedPanels({super.key, required this.cards, this.now});
  final List<HomeCard> cards; // removedPanels() 的结果
  final DateTime? now;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    Future<void> pick() async {
      final card = await showActionSheet<HomeCard>(context, title: '点一个，放回主页', actions: [
        for (final c in cards) SheetAction(Icons.restore_rounded, '${c.title} · 移除于 ${formatWhen(c.removedAt, now: now)}', value: c),
      ]);
      if (card != null && context.mounted) await revivePanel(context, ref, card);
    }

    final p = context.palette;
    return RiseSwitcher(
      child: cards.isEmpty
          ? const SizedBox.shrink(key: ValueKey('none'))
          : Pressable(
              key: const ValueKey('removed'),
              onTap: pick,
              semanticLabel: '${cards.length} 个最近移除的面板，点开找回',
              child: ConstrainedBox(
                constraints: const BoxConstraints(minHeight: A11y.minTap),
                child: Row(children: [
                  Icon(Icons.restore_rounded, size: Fs.md, color: p.text3),
                  const SizedBox(width: Sp.x2),
                  Expanded(
                    child: Text('${cards.length} 个最近移除的面板 · 30 天内可找回',
                        style: context.text.bodySmall?.copyWith(color: p.text2), maxLines: 1, overflow: TextOverflow.ellipsis),
                  ),
                  Icon(Icons.chevron_right_rounded, size: Fs.lg, color: p.text3),
                ]),
              ),
            ),
    );
  }
}
