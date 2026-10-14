// 主页上的一张面板（v2.78 从 home_screen.dart 拆出）：卡头 = 标题 + 更新时间 + 刷新 / 更多（编辑、刷新记录、移除），
// 下面是面板的内容块。刷新中内容变淡（Dimmed），刷完关键数字（ValueTile → CountUp）从旧值滚到新值。
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../blocks/block_view.dart';
import '../../core/api.dart';
import '../../core/resource.dart';
import '../../models/resources.dart';
import '../../theme/app_theme.dart';
import '../../theme/tokens.dart';
import '../../ui/glass.dart';
import '../../ui/motion.dart';
import '../../ui/sheets.dart';
import '../me/task_form.dart';
import '../me/task_wall.dart';
import 'removed_panels.dart';
import 'stack_card.dart';

String hm(DateTime? t) => t == null ? '' : '${t.hour.toString().padLeft(2, '0')}:${t.minute.toString().padLeft(2, '0')}';

class PanelCard extends ConsumerWidget {
  const PanelCard({super.key, required this.card, required this.task, required this.refreshing});
  final HomeCard card;

  /// 面板背后的任务（碰壁条读它）；任务列表还没到 = null。
  final ScheduledTask? task;
  final bool refreshing;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final p = context.palette;
    Future<void> refresh() async {
      await ref.read(apiProvider).post('/api/tasks/${card.taskId}/run');
      await ref.read(tasksProvider.notifier).reload();
    }

    // v2.17 移除可以撤销 / 30 天内找回（新面板弹层里），所以不再弹危险确认
    Future<void> remove() => removePanel(context, ref, card);

    // 改标题/刷新指令/频率：和任务详情同一张表单；改名由服务端同步到卡片，所以之后重拉一次卡片
    Future<void> edit() async {
      final task = ref.read(tasksProvider).value?.where((t) => t.id == card.taskId).firstOrNull;
      if (task == null) return;
      final changes = await showTaskForm(context, task: task);
      if (changes == null || changes.isEmpty) return;
      await ref.read(tasksProvider.notifier).patch(task.id, changes);
      await ref.read(cardsProvider.notifier).reload();
    }

    void menu() => showActionSheet<void>(context, title: card.title, actions: [
          if (card.taskId != null) ...[
            SheetAction(Icons.edit_outlined, '编辑面板', onTap: edit),
            SheetAction(Icons.history_rounded, '刷新记录', onTap: () => context.push('/me/tasks/${card.taskId}')),
          ],
          SheetAction(Icons.delete_outline_rounded, '移除', onTap: remove, danger: true),
        ]);

    return StackCard(
      title: card.title,
      // 刷新中 ↔ 新时间：旧字上滑淡出、新字浮上来（刷完那一下看得见“更新了”）；小图标钮可点区域仍 ≥ A11y.minTap
      trailing: Row(mainAxisSize: MainAxisSize.min, children: [
        SwapSwitcher(
            child: Text(refreshing ? '刷新中…' : hm(card.updatedAt),
                key: ValueKey(refreshing ? '' : hm(card.updatedAt)), style: context.text.labelSmall)),
        if (card.taskId != null)
          IconButton(
            onPressed: refreshing ? null : refresh,
            tooltip: '刷新',
            icon: AnimatedRotation(
              turns: refreshing ? 1 : 0,
              duration: refreshing ? context.motion(Motion.spin) : Duration.zero,
              child: Icon(Icons.refresh_rounded, size: Fs.lg, color: p.text3),
            ),
          ),
        IconButton(onPressed: menu, tooltip: '更多', icon: Icon(Icons.more_horiz_rounded, size: Fs.lg, color: p.text3)),
      ]),
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        // v2.15 碰壁：内容还是上一次的，上面一条说清卡在哪、要不要你处理（task_wall.dart）
        if (task != null) WallNotice(task: task!, onRetry: refreshing ? null : refresh, padding: const EdgeInsets.only(bottom: Sp.x3)),
        Dimmed(dimmed: refreshing, child: BlockList(card.blocks)),
      ]),
    );
  }
}

/// 还没有要你处理的事时的那张引导卡：衬线大标题 + 一句话 + 去连接。
class ConnectCard extends StatelessWidget {
  const ConnectCard({super.key});

  @override
  Widget build(BuildContext context) => StackCard(
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('我还能做更多', style: context.text.headlineMedium),
          const SizedBox(height: Sp.x1),
          Text('连接邮箱和日历后，我会在这里主动提醒你要处理的事。', style: context.text.bodyMedium?.copyWith(color: context.palette.text2)),
          const SizedBox(height: Sp.x4),
          PillButton(label: '去连接', icon: Icons.hub_outlined, onTap: () => context.push('/me/connectors')),
        ]),
      );
}
