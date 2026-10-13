// 用户消息里点名的标签（气泡上方一排胶囊）：
// - `$技能`（v1.81）：这次按哪个技能做，点一下打开技能页里的这条（看正文 / 改）。规则在服务器 app/skill_mentions.py。
// - `@子助手`（v1.91）：这件事交给了子助手（结果在回复里的子任务卡上），不可点。规则在服务器 app/agent_mentions.py。
// - 来自 X（v2.23）：别的项目 / 主聊天的助手替用户转交来的，点一下回到来源那段对话（BlockActions.onOpenConversation）。
// - 追问（v1.97）：在子任务卡上点“追问”发的消息，“追问 · 标题”；上下文不在了图标换成断开。
import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../models/block.dart';
import '../models/delegate.dart';
import '../theme/app_theme.dart';
import '../theme/tokens.dart';
import '../ui/glass.dart';
import '../ui/motion.dart';
import 'block_actions.dart';

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
        label: agentChipSemantics(block),
        excludeSemantics: true,
        child: _Pill(
            icon: block.target == null
                ? Icons.call_split_rounded
                : (block.gone ? Icons.link_off_rounded : Icons.reply_rounded),
            label: agentChipLabel(block)),
      );
}

class OriginChip extends StatelessWidget {
  const OriginChip(this.block, {super.key});
  final OriginBlock block;

  @override
  Widget build(BuildContext context) {
    final open = BlockActions.of(context)?.onOpenConversation;
    final cid = block.conversationId;
    final pill = _Pill(icon: Icons.forward_rounded, label: block.label);
    if (open == null || cid == null) return Semantics(label: block.semantics, excludeSemantics: true, child: pill);
    return Pressable(semanticLabel: block.semantics, onTap: () => open(cid, block.projectId), child: pill);
  }
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
