// 用户消息里点名的标签（气泡上方一排胶囊）：
// - `$技能`（v1.81）：这次按哪个技能做，点一下打开技能页里的这条（看正文 / 改）。规则在服务器 app/skill_mentions.py。
// - `@子助手`（v1.91）：这件事交给了子助手（结果在回复里的子任务卡上），不可点。规则在服务器 app/agent_mentions.py。
import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../models/block.dart';
import '../theme/app_theme.dart';
import '../theme/tokens.dart';
import '../ui/glass.dart';
import '../ui/motion.dart';

class SkillChip extends StatelessWidget {
  const SkillChip(this.block, {super.key});
  final SkillBlock block;

  @override
  Widget build(BuildContext context) => Pressable(
        semanticLabel: '技能 ${block.name}',
        onTap: () => context.push('/me/skills/${Uri.encodeComponent(block.id)}'),
        child: _Pill(icon: Icons.auto_awesome_rounded, label: block.name),
      );
}

class AgentChip extends StatelessWidget {
  const AgentChip(this.block, {super.key});
  final AgentBlock block;

  @override
  Widget build(BuildContext context) => Semantics(
        label: '交给${block.name}',
        excludeSemantics: true,
        child: _Pill(icon: Icons.call_split_rounded, label: block.name),
      );
}

class _Pill extends StatelessWidget {
  const _Pill({required this.icon, required this.label});
  final IconData icon;
  final String label;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: Sp.x3, vertical: Sp.x1),
      decoration: BoxDecoration(color: context.tileFill, borderRadius: BorderRadius.circular(Radii.full)),
      child: Row(mainAxisSize: MainAxisSize.min, children: [
        Icon(icon, size: 14, color: p.text2),
        const SizedBox(width: Sp.x1),
        Flexible(
          child: Text(label, style: context.text.bodySmall?.copyWith(color: p.text2), maxLines: 1, overflow: TextOverflow.ellipsis),
        ),
      ]),
    );
  }
}
