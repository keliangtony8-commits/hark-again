// 主页“今天”卡（v2.78）：今天排着的任务按钟点一行一件（today_agenda.dart 定规则）。只在今天真有任务时出现——
// 没有就整张不画（不再有“今天没有排定的任务”空卡 + 同一句摘要的重复）。卡头 = “今天” + 摘要小字。
// 行首等宽钟点列，下一个用正文色加粗、跑完的整行变淡（失败不淡）；失败/暂停只把那两个字染警示色；点行进任务详情。
// “帮我准备今天”是主页输入框的第一个建议，“每天早上自动准备”在新面板弹层里（new_panel.dart）——不在这张卡上堆按钮。
import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../../models/resources.dart';
import '../../theme/app_theme.dart';
import '../../theme/tokens.dart';
import '../../ui/glass_mode.dart';
import '../../ui/kit.dart';
import '../../ui/motion.dart';
import 'stack_card.dart';
import 'today_agenda.dart';

class TodayCard extends StatelessWidget {
  const TodayCard({super.key, required this.tasks, this.now});
  final List<ScheduledTask> tasks;
  final DateTime? now;

  @override
  Widget build(BuildContext context) {
    final now = this.now ?? DateTime.now();
    final items = todayAgenda(tasks, now);
    final nowAt = agendaNowAt(items, now);
    return RiseSwitcher(
      child: items.isEmpty
          ? const SizedBox.shrink(key: ValueKey('none'))
          : StackCard(
              key: const ValueKey('today'),
              title: '今天',
              trailing: CardNote(agendaSummary(items)),
              // 细线对齐标题边（行首是钟点列不是图标）；“现在”那一格换成 _NowLine，替掉细线而不是多插一行。
              separator: (i) => i == nowAt
                  ? FadeSlideIn(delay: Motion.stagger(i, from: 1), child: _NowLine(at: now))
                  : Divider(indent: Sp.x4 + Layout.agendaTime + Sp.x4, endIndent: 0, color: context.hairline),
              rows: [
                for (var i = 0; i < items.length; i++) FadeSlideIn(delay: Motion.stagger(i, from: 1), child: _AgendaRow(item: items[i])),
              ],
            ),
    );
  }
}

class _AgendaRow extends StatelessWidget {
  const _AgendaRow({required this.item});
  final AgendaItem item;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final next = item.state == AgendaState.next;
    final hint = agendaHint(item);
    return ListRow(
      dimmed: item.faded,
      leading: SizedBox(
        width: Layout.agendaTime,
        child: Text(item.time,
            style: context.text.titleSmall?.copyWith(color: next ? p.text : p.text2, fontWeight: next ? Weights.title : null, fontFeatures: const [FontFeature.tabularFigures()])), // 钟点列上下对齐
      ),
      title: item.task.name,
      subtitle: agendaDetail(item),
      problem: agendaProblem(item),
      trailing: hint.isEmpty ? const SizedBox.shrink() : SwapSwitcher(child: RowHint(hint, key: ValueKey(hint))),
      onTap: () => context.push('/me/tasks/${item.task.id}'),
    );
  }
}

/// 日程里“此刻”的位置：钟点列写“现在”，标题边起一颗小点 + 一条细线延到行尾。只用正文二级/三级色，
/// 不用强调色、不循环闪——它是方位，不是提醒。读屏念“现在 HH:MM”。
class _NowLine extends StatelessWidget {
  const _NowLine({required this.at});
  final DateTime at;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    return Semantics(
      label: '现在 ${clockOf(at)}',
      excludeSemantics: true,
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: Sp.x4, vertical: Sp.x1),
        child: Row(children: [
          SizedBox(
            width: Layout.agendaTime,
            child: Text('现在', style: context.text.labelSmall?.copyWith(color: p.text2, fontWeight: Weights.title)),
          ),
          const SizedBox(width: Sp.x4),
          Container(width: Layout.nowDot, height: Layout.nowDot, decoration: BoxDecoration(color: p.text2, shape: BoxShape.circle)),
          Expanded(child: Container(height: 1, color: p.text3)),
        ]),
      ),
    );
  }
}
