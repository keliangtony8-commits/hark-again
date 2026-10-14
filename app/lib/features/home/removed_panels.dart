// v2.17 移除的面板可以找回（规则在 backend app/panel_trash.py：30 天内，找回后做法都在、马上重新取数据）。
// 这里是客户端唯一入口：
// - removePanel：面板“更多 → 移除”。可撤销，所以不再弹危险确认；底部一条“已移除「X」· 撤销”。
// - 找回：新面板弹层（new_panel.dart）底部列出 removedPanels()，点一个 → revivePanel。v2.78 起主页上不再单独占一行。
// 网页版 features/home/RemovedPanels.tsx 同规则。
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api.dart';
import '../../core/resource.dart';
import '../../models/resources.dart';
import '../../ui/kit.dart';

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
