// “为你准备”里的一张主动建议卡：标题 + 内容块 + 一排等宽胶囊（忽略 / [去处] / 去做，最后一个是主按钮）。
// 去处（HomeCard.target）是服务端说“这件事在客户端的哪一页看”，比如预算提醒 → 用量页。
// route 里的 {task} 换成卡上的 task_id（任务失败提醒 → 那个任务的详情；卡上没有 task_id 就退到列表）。
// 标题右边一个“稍后提醒”小钮（features/home/card_snooze.dart）：先收起，到点再放回。
// 助手提议的卡（card.offered）：标题上方一行“可以替你做”，主按钮用卡上的字（actionText），点了发指令进新对话并把卡收起；
// 系统提醒点“去做”不收起（恢复后服务端自己收起）。
// 映射只在 cardTargets 一处；不认识的值当没有（老 App 遇到新服务端不出错）。网页版 lib/cardTargets.ts 同一张表。
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../blocks/block_view.dart';
import '../../core/resource.dart';
import '../../models/resources.dart';
import '../../theme/app_theme.dart';
import '../../theme/tokens.dart';
import '../../ui/glass.dart';
import '../../ui/kit.dart';
import 'card_snooze.dart';
import 'inbox.dart';

typedef CardTarget = ({String label, IconData icon, String route});

const cardTargets = <String, CardTarget>{
  'usage': (label: '查看用量', icon: Icons.data_usage_rounded, route: '/me/usage'),
  'tasks': (label: '查看任务', icon: Icons.event_repeat_rounded, route: '/me/tasks/{task}'),
};

CardTarget? cardTarget(String? id) => id == null ? null : cardTargets[id];

String cardRoute(CardTarget t, HomeCard card) {
  const slot = '/{task}';
  if (!t.route.contains(slot)) return t.route;
  final id = card.taskId;
  return id == null ? t.route.replaceAll(slot, '') : t.route.replaceAll('{task}', id);
}

class ActionCard extends ConsumerWidget {
  const ActionCard({super.key, required this.card, required this.onDo});
  final HomeCard card;
  final void Function(String) onDo;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final target = cardTarget(card.target);

    Future<void> dismiss() async {
      await ref.read(cardsProvider.notifier).patch(card.id, {'dismissed': true});
      await ref.read(inboxProvider.notifier).refresh(); // 忽略的卡不再算未读
    }

    void open(CardTarget t) {
      if (card.unread) ref.read(inboxProvider.notifier).markRead([card.id]).ignore();
      // “我的”下的去处盖在外壳上（push），返回回到主页；聊天等 Tab 内去处直接切过去
      final route = cardRoute(t, card);
      route.startsWith('/me') ? context.push(route) : context.go(route);
    }

    Future<void> doIt() async {
      final prompt = card.actionPrompt!;
      if (card.offered) {
        // 先拿到 notifier 再跳走：onDo 会切到聊天，这张卡的 context 可能随即失效
        final cards = ref.read(cardsProvider.notifier), inbox = ref.read(inboxProvider.notifier);
        onDo(prompt);
        await cards.patch(card.id, {'dismissed': true});
        await inbox.refresh();
      } else {
        onDo(prompt);
      }
    }

    // 按钮一排等宽：忽略永远是次按钮；有“去做”时它是主按钮，否则去处是主按钮
    final buttons = <Widget>[
      PillButton(label: '忽略', onTap: dismiss),
      if (target != null) PillButton(label: target.label, icon: target.icon, primary: card.actionPrompt == null, onTap: () => open(target)),
      if (card.actionPrompt != null) PillButton(label: card.actionText, primary: true, onTap: doIt),
    ];
    // 稍后钮是小图标，可点区域仍 ≥ A11y.minTap；用负边距把它的空白吃进卡片内边距，标题行不被撑高
    return Padding(
      padding: const EdgeInsets.only(bottom: Layout.cardGap),
      child: GlassCard(
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            IconBadge(target?.icon ?? Icons.auto_awesome_rounded),
            const SizedBox(width: Sp.x3),
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
                if (card.offered) Text('可以替你做', style: context.text.labelSmall?.copyWith(color: context.palette.text3)),
                Text(card.title, style: context.text.titleMedium),
              ]),
            ),
            Transform.translate(
              offset: const Offset(Sp.x3, 0),
              child: IconButton(
                onPressed: () => showSnoozeSheet(context, ref, card),
                tooltip: '稍后提醒',
                icon: Icon(Icons.snooze_rounded, size: Fs.lg, color: context.palette.text3),
              ),
            ),
          ]),
          if (card.blocks.isNotEmpty) ...[const SizedBox(height: Sp.x3), BlockList(card.blocks)],
          const SizedBox(height: Sp.x4),
          Row(children: [
            for (var i = 0; i < buttons.length; i++) ...[
              if (i > 0) const SizedBox(width: Sp.x2),
              Expanded(child: buttons[i]),
            ],
          ]),
        ]),
      ),
    );
  }
}
