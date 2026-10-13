// 用量页“自动选模型”一节：本月自动轮约省多少（或多花）、两档各走了多少轮（分段条）、分类器花了多少。
// 数字全来自报表的 router（后端 app/router_stats.py）；本文件只排版，文案规则在 models/usage.dart。
import 'package:flutter/material.dart';

import '../../models/usage.dart';
import '../../theme/app_theme.dart';
import '../../theme/tokens.dart';
import '../../ui/kit.dart';
import '../../ui/motion.dart';

class RouterUsageCard extends StatelessWidget {
  const RouterUsageCard({super.key, required this.usage, required this.currency, required this.money});
  final RouterUsage usage;
  final String currency;
  final bool money; // 报表有没有定价（没定价时分类器花费不写钱）

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final u = usage;
    final head = routerHeadline(u, currency);
    final split = routerSplitLine(u);
    final cost = routerCostLine(u, currency, money: money);
    return AppCard(
      key: const Key('router-usage'),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Semantics(
          label: '自动选模型，$head，$split',
          excludeSemantics: true,
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text('自动选模型', style: context.text.labelSmall),
            const SizedBox(height: Sp.x1),
            CountUp(head, style: context.text.headlineMedium?.copyWith(color: u.losing ? p.warning : p.text)),
            Text(split, style: context.text.bodySmall),
          ]),
        ),
        const SizedBox(height: Sp.x3),
        MeterBar(key: const Key('router-share'), value: u.simpleShare, color: p.ink),
        const SizedBox(height: Sp.x2),
        Row(children: [
          Expanded(child: Text('${u.simpleModel.isEmpty ? '简单档' : u.simpleModel} ${(u.simpleShare * 100).round()}%', style: context.text.bodySmall)),
          Text('${u.complexModel.isEmpty ? '复杂档' : u.complexModel} ${100 - (u.simpleShare * 100).round()}%', style: context.text.bodySmall),
        ]),
        const SizedBox(height: Sp.x3),
        Text(cost, style: context.text.bodySmall?.copyWith(color: p.text2)),
        const SizedBox(height: Sp.x1),
        Text(routerNote(u), key: const Key('router-note'), style: context.text.bodySmall?.copyWith(color: u.losing ? p.warning : p.text3)),
      ]),
    );
  }
}
